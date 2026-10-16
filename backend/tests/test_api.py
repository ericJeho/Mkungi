"""API flow against local storage and against a fake Supabase."""

import io
import json
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

    def _filters(self, request: httpx.Request) -> dict[str, str]:
        q = parse_qs(urlsplit(str(request.url)).query)
        return {k: v[0].removeprefix("eq.") for k, v in q.items() if k != "select"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        authed = request.headers.get("apikey") == SECRET
        if path == "/rest/v1/conversions":
            assert authed
            if request.method == "POST":
                row = {"created_at": "2026-10-16T00:00:00Z", **json.loads(request.content)}
                self.rows[row["id"]] = row
                return httpx.Response(201, json=[row])
            matches = [r for r in self.rows.values() if all(r.get(k) == v for k, v in self._filters(request).items())]
            if request.method == "PATCH":
                for r in matches:
                    r.update(json.loads(request.content))
            return httpx.Response(200, json=matches)

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
