"""API flow against local storage and against a fake Supabase."""

import io
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlsplit

import cv2
import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient

from app import main
from app.storage import LocalStore, SupabaseStore
from tests.test_pipeline import FakeEngine, _invoice_image

SUPABASE_URL = "https://mkungi-test.supabase.co"
SECRET = "sb_secret_test"


@pytest.fixture
def invoice_png() -> bytes:
    ok, buf = cv2.imencode(".png", _invoice_image())
    assert ok
    return buf.tobytes()


class FakeSupabase:
    """Just enough of PostgREST and Storage for SupabaseStore."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.objects: dict[str, bytes] = {}
        self.tokens: dict[str, str] = {}

    def _match(self, request: httpx.Request) -> list[dict]:
        """Apply PostgREST-style filters (eq, gte, lt, in), order and limit."""
        q = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        rows = list(self.rows.values())
        for col, expr in q.items():
            if col in ("select", "order", "limit"):
                continue
            op, _, val = expr.partition(".")
            tests = {
                "eq": lambda v, val=val: v == val,
                "gte": lambda v, val=val: v is not None and v >= val,
                "lt": lambda v, val=val: v is not None and v < val,
                "in": lambda v, val=val: v in val.strip("()").split(","),
            }
            rows = [r for r in rows if tests[op](r.get(col))]
        if "order" in q:
            rows.sort(key=lambda r: r[q["order"].split(".")[0]])
        return rows[: int(q["limit"])] if "limit" in q else rows

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        authed = request.headers.get("apikey") == SECRET
        if path == "/rest/v1/conversions":
            assert authed
            if request.method == "POST":
                row = {"created_at": datetime.now(timezone.utc).isoformat(), **json.loads(request.content)}
                self.rows[row["id"]] = row
                return httpx.Response(201, json=[row])
            matches = self._match(request)
            if request.method == "PATCH":
                for r in matches:
                    r.update(json.loads(request.content))
            if request.method == "DELETE":
                for r in matches:
                    del self.rows[r["id"]]
            return httpx.Response(200, json=matches)

        if request.method == "DELETE" and path.startswith("/storage/v1/object/"):
            assert authed
            bucket = path.removeprefix("/storage/v1/object/")
            for prefix in json.loads(request.content)["prefixes"]:
                self.objects.pop(f"{bucket}/{prefix}", None)
            return httpx.Response(200, json=[])

        for prefix, kind in (
            ("/storage/v1/object/upload/sign/", "upload_sign"),
            ("/storage/v1/object/sign/", "sign"),
            ("/storage/v1/object/", "object"),
        ):
            if path.startswith(prefix):
                key = path[len(prefix) :]
                token = request.url.params.get("token")
                if kind == "upload_sign" and request.method == "POST":
                    assert authed
                    self.tokens["up"] = key
                    return httpx.Response(200, json={"url": f"/object/upload/sign/{key}?token=up"})
                if kind == "upload_sign" and request.method == "PUT":
                    assert token == "up" and self.tokens["up"] == key  # no secret needed
                    self.objects[key] = request.content
                    return httpx.Response(200, json={"Key": key})
                if kind == "sign" and request.method == "POST":
                    assert authed
                    self.tokens["dl"] = key
                    return httpx.Response(200, json={"signedURL": f"/object/sign/{key}?token=dl"})
                if kind == "sign" and request.method == "GET":
                    assert token == "dl" and self.tokens["dl"] == key
                    return httpx.Response(200, content=self.objects[key])
                assert authed
                if request.method == "POST":
                    self.objects[key] = request.content
                    return httpx.Response(200, json={"Key": key})
                if key not in self.objects:
                    return httpx.Response(400, json={"error": "not_found"})
                return httpx.Response(200, content=self.objects[key])
        return httpx.Response(404)


@pytest.fixture
def local_store(tmp_path):
    return LocalStore(tmp_path)


@pytest.fixture
def fake_supabase():
    fake = FakeSupabase()
    http = httpx.Client(transport=httpx.MockTransport(fake.handler))
    return fake, http, SupabaseStore(SUPABASE_URL, SECRET, "uploads", "outputs", client=http)


@pytest.fixture
def client():
    main.app.dependency_overrides[main.ocr_engine] = FakeEngine
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def test_local_flow(client, local_store, invoice_png):
    main.app.dependency_overrides[main.store] = lambda: local_store

    r = client.post("/v1/conversions", json={"filename": "invoice.png", "output_format": "docx"})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "awaiting_upload" and "input_path" not in job

    # Processing before the upload is refused.
    assert client.post(f"/v1/conversions/{job['id']}/process").status_code == 409

    up = job["upload"]
    assert client.request(up["method"], up["url"], content=invoice_png).status_code == 204

    done = client.post(f"/v1/conversions/{job['id']}/process").json()
    assert done["status"] == "done", done
    assert done["doc_type"] == "invoice" and done["tables"] == 1 and done["output_file"] == "invoice.docx"
    assert client.get(f"/v1/conversions/{job['id']}").json()["status"] == "done"

    dl = client.get(f"/v1/conversions/{job['id']}/download")
    assert dl.status_code == 200
    Document(io.BytesIO(dl.content))

    # A job runs once; uploads are closed afterwards.
    assert client.post(f"/v1/conversions/{job['id']}/process").status_code == 409
    assert client.put(up["url"], content=b"x").status_code == 409


def test_supabase_flow(client, fake_supabase, invoice_png):
    fake, http, store = fake_supabase
    main.app.dependency_overrides[main.store] = lambda: store

    job = client.post("/v1/conversions", json={"filename": "invoice.png"}).json()
    up = job["upload"]
    assert up["url"].startswith(f"{SUPABASE_URL}/storage/v1/object/upload/sign/uploads/{job['id']}/")

    assert up["headers"] == {"Content-Type": "image/png"}

    # The browser uploads straight to Storage; the API never sees the bytes.
    assert http.request(up["method"], up["url"], content=invoice_png, headers=up["headers"]).status_code == 200

    done = client.post(f"/v1/conversions/{job['id']}/process").json()
    assert done["status"] == "done", done
    assert done["output_format"] == "docx"  # auto picked Word for an invoice
    assert fake.rows[job["id"]]["output_path"] == f"{job['id']}/invoice.docx"

    dl = client.get(f"/v1/conversions/{job['id']}/download", follow_redirects=False)
    assert dl.status_code == 307
    location = dl.headers["location"]
    assert location.startswith(f"{SUPABASE_URL}/storage/v1/object/sign/outputs/") and "download=invoice.docx" in location
    Document(io.BytesIO(http.get(location).content))


def test_supabase_missing_upload(client, fake_supabase):
    _, _, store = fake_supabase
    main.app.dependency_overrides[main.store] = lambda: store
    job = client.post("/v1/conversions", json={"filename": "scan.pdf"}).json()
    r = client.post(f"/v1/conversions/{job['id']}/process")
    assert r.status_code == 409 and "not been uploaded" in r.json()["detail"]


def test_failed_conversion_is_reported(client, local_store):
    main.app.dependency_overrides[main.store] = lambda: local_store
    job = client.post("/v1/conversions", json={"filename": "broken.png"}).json()
    client.put(job["upload"]["url"], content=b"not an image")
    done = client.post(f"/v1/conversions/{job['id']}/process").json()
    assert done["status"] == "failed" and "corrupt" in done["error"]


def test_validation(client, local_store):
    main.app.dependency_overrides[main.store] = lambda: local_store
    assert client.post("/v1/conversions", json={"filename": "x.exe"}).status_code == 415
    assert client.post("/v1/conversions", json={"filename": "x.png", "output_format": "pdf"}).status_code == 422
    assert client.get("/v1/conversions/not-a-uuid").status_code == 404
    assert client.get("/v1/conversions/00000000-0000-0000-0000-000000000000").status_code == 404


def _backdate(store, job_id: str, hours: float) -> None:
    """Make a job look older than it is."""
    store.update(job_id, created_at=(datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat())


@pytest.fixture(params=["local", "supabase"])
def any_store(request, tmp_path, fake_supabase):
    store = LocalStore(tmp_path) if request.param == "local" else fake_supabase[2]
    main.app.dependency_overrides[main.store] = lambda: store
    return store


def test_rate_limit_per_visitor(client, any_store, monkeypatch):
    monkeypatch.setattr(main.settings, "max_conversions_per_hour", 2)
    for _ in range(2):
        assert client.post("/v1/conversions", json={"filename": "a.png"}).status_code == 201
    r = client.post("/v1/conversions", json={"filename": "a.png"})
    assert r.status_code == 429 and r.headers["retry-after"] == "3600"
    # Jobs older than an hour no longer count.
    for job in any_store.expired(datetime.now(timezone.utc).isoformat(), 10):
        _backdate(any_store, job["id"], 2)
    assert client.post("/v1/conversions", json={"filename": "a.png"}).status_code == 201


def test_rate_limit_keys_on_client(any_store, monkeypatch):
    monkeypatch.setattr(main.settings, "max_conversions_per_hour", 1)
    main.app.dependency_overrides[main.ocr_engine] = FakeEngine
    try:
        a = TestClient(main.app, client=("10.0.0.1", 1111))
        b = TestClient(main.app, client=("10.0.0.2", 2222))
        assert a.post("/v1/conversions", json={"filename": "a.png"}).status_code == 201
        assert a.post("/v1/conversions", json={"filename": "a.png"}).status_code == 429
        assert b.post("/v1/conversions", json={"filename": "b.png"}).status_code == 201
        job = b.get("/v1/conversions/" + any_store.expired("9999", 10)[-1]["id"]).json()
        assert "client_hash" not in job  # never exposed
    finally:
        main.app.dependency_overrides.clear()


def test_cleanup_deletes_old_jobs_and_files(client, any_store, fake_supabase, invoice_png, monkeypatch):
    monkeypatch.setattr(main.settings, "cron_secret", "s3cret")
    old = client.post("/v1/conversions", json={"filename": "old.png", "output_format": "docx"}).json()
    up = old["upload"]
    if up["url"].startswith("/"):
        client.request(up["method"], up["url"], content=invoice_png)
    else:
        any_store.http.request(up["method"], up["url"], content=invoice_png, headers=up["headers"])
    assert client.post(f"/v1/conversions/{old['id']}/process").json()["status"] == "done"
    new = client.post("/v1/conversions", json={"filename": "new.png"}).json()
    _backdate(any_store, old["id"], 25)

    if isinstance(any_store, SupabaseStore):
        assert sum(old["id"] in k for k in fake_supabase[0].objects) == 2  # upload + output

    assert client.get("/v1/maintenance/cleanup").status_code == 401
    assert client.get("/v1/maintenance/cleanup", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/v1/maintenance/cleanup", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200 and r.json()["deleted"] == 1

    assert client.get(f"/v1/conversions/{old['id']}").status_code == 404
    assert client.get(f"/v1/conversions/{new['id']}").status_code == 200
    if isinstance(any_store, SupabaseStore):
        assert any(old["id"] in k for k in fake_supabase[0].objects) is False  # upload and output both removed
    else:
        assert not (any_store.root / "jobs" / old["id"]).exists()


def test_cleanup_disabled_without_secret(client, local_store):
    main.app.dependency_overrides[main.store] = lambda: local_store
    assert client.get("/v1/maintenance/cleanup", headers={"Authorization": "Bearer "}).status_code == 401
