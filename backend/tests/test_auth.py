"""Sign-in: token verification and per-user job isolation."""

import time
import uuid

import cv2
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app import main
from app.auth import InvalidToken, SupabaseAuth
from app.storage import SupabaseStore
from tests.test_api import SECRET, SUPABASE_URL, FakeSupabase
from tests.test_pipeline import FakeEngine, _invoice_image

ISSUER = f"{SUPABASE_URL}/auth/v1"
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def _jwk(private_key, kid: str) -> dict:
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    return {**jwk, "kid": kid, "alg": "ES256", "use": "sig"}


def token(sub: str | None = None, *, key=KEY, kid="k1", **overrides) -> str:
    claims = {
        "sub": sub or str(uuid.uuid4()),
        "email": "user@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
        **overrides,
    }
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})


LEGACY_USER = "7b0c4b8e-0000-4000-8000-000000000001"
LEGACY_TOKEN = jwt.encode({"sub": LEGACY_USER}, "legacy-secret", algorithm="HS256")


class FakeAuthServer:
    def __init__(self):
        self.jwks_requests = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/.well-known/jwks.json":
            self.jwks_requests += 1
            return httpx.Response(200, json={"keys": [_jwk(KEY, "k1")]})
        if request.url.path == "/auth/v1/user":
            assert request.headers["apikey"] == SECRET
            if request.headers.get("authorization") == f"Bearer {LEGACY_TOKEN}":
                return httpx.Response(200, json={"id": LEGACY_USER, "email": "legacy@example.com"})
            return httpx.Response(401, json={"msg": "invalid JWT"})
        return httpx.Response(404)


@pytest.fixture
def auth_server():
    return FakeAuthServer()


@pytest.fixture
def verifier(auth_server):
    return SupabaseAuth(SUPABASE_URL, SECRET, client=httpx.Client(transport=httpx.MockTransport(auth_server.handler)))


def test_valid_token(verifier, auth_server):
    user = verifier.verify(token("11111111-1111-4111-8111-111111111111"))
    assert user.id == "11111111-1111-4111-8111-111111111111" and user.email == "user@example.com"
    verifier.verify(token())
    assert auth_server.jwks_requests == 1  # public keys are cached


@pytest.mark.parametrize(
    "bad",
    [
        token(exp=int(time.time()) - 10),  # expired
        token(aud="someone-else"),
        token(iss="https://evil.supabase.co/auth/v1"),
        token(role="anon"),
        token(key=OTHER_KEY),  # right kid, wrong signature
        token(kid="unknown"),
        "not-a-jwt",
        jwt.encode({"sub": "x"}, None, algorithm="none"),
        jwt.encode({"sub": "x"}, "guessed-secret", algorithm="HS256"),
    ],
)
def test_rejected_tokens(verifier, bad):
    with pytest.raises(InvalidToken):
        verifier.verify(bad)


def test_legacy_secret_tokens_are_checked_by_supabase(verifier):
    assert verifier.verify(LEGACY_TOKEN).id == LEGACY_USER


@pytest.fixture
def api(verifier):
    fake = FakeSupabase()
    http = httpx.Client(transport=httpx.MockTransport(fake.handler))
    store = SupabaseStore(SUPABASE_URL, SECRET, "uploads", "outputs", client=http)
    main.app.dependency_overrides.update(
        {main.store: lambda: store, main.auth: lambda: verifier, main.ocr_engine: FakeEngine}
    )
    yield TestClient(main.app), http
    main.app.dependency_overrides.clear()


def _as(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def test_sign_in_required(api):
    client, _ = api
    r = client.post("/v1/conversions", json={"filename": "a.png"})
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert client.post("/v1/conversions", json={"filename": "a.png"}, headers=_as("junk")).status_code == 401
    assert client.get("/v1/conversions", headers=_as(token(exp=int(time.time()) - 1))).status_code == 401
    assert client.get("/health").json()["status"] == "ok"  # health stays public


def test_jobs_belong_to_their_user(api):
    client, http = api
    alice, bob = token("aaaaaaaa-0000-4000-8000-000000000001"), token("bbbbbbbb-0000-4000-8000-000000000002")

    job = client.post("/v1/conversions", json={"filename": "invoice.png"}, headers=_as(alice)).json()
    assert "user_id" not in job and "client_hash" not in job
    ok, png = cv2.imencode(".png", _invoice_image())
    up = job["upload"]
    assert http.request(up["method"], up["url"], content=png.tobytes(), headers=up["headers"]).status_code == 200

    # Bob can't see, run or download Alice's job; it looks like it doesn't exist.
    for method, path in [
        ("GET", f"/v1/conversions/{job['id']}"),
        ("POST", f"/v1/conversions/{job['id']}/process"),
        ("GET", f"/v1/conversions/{job['id']}/download-url"),
        ("GET", f"/v1/conversions/{job['id']}/download"),
    ]:
        assert client.request(method, path, headers=_as(bob)).status_code == 404, path
    assert client.get("/v1/conversions", headers=_as(bob)).json() == []

    done = client.post(f"/v1/conversions/{job['id']}/process", headers=_as(alice)).json()
    assert done["status"] == "done"
    mine = client.get("/v1/conversions", headers=_as(alice)).json()
    assert [j["id"] for j in mine] == [job["id"]] and "user_id" not in mine[0]

    link = client.get(f"/v1/conversions/{job['id']}/download-url", headers=_as(alice)).json()
    assert link["filename"] == "invoice.docx"
    assert link["url"].startswith(f"{SUPABASE_URL}/storage/v1/object/sign/outputs/")
    assert http.get(link["url"]).status_code == 200


def test_rate_limit_is_per_account(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(main.settings, "max_conversions_per_hour", 1)
    alice, bob = token(), token()
    assert client.post("/v1/conversions", json={"filename": "a.png"}, headers=_as(alice)).status_code == 201
    assert client.post("/v1/conversions", json={"filename": "a.png"}, headers=_as(alice)).status_code == 429
    # Same IP (the test client), different account: not limited.
    assert client.post("/v1/conversions", json={"filename": "b.png"}, headers=_as(bob)).status_code == 201
