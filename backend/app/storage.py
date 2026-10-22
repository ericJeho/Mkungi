"""Where jobs and files live.

``LocalStore`` keeps everything on disk (development, tests, Docker).
``SupabaseStore`` keeps job rows in Postgres and files in Supabase Storage
(production on Vercel). Uploads to Supabase go straight from the browser to
Storage through a signed URL, so files never pass through the serverless
function's 4.5 MB request limit.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from app.config import Settings


class JobNotFound(Exception):
    pass


class InputMissing(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store(Protocol):
    def create(
        self, filename: str, requested_format: str, client_hash: str | None = None, user_id: str | None = None
    ) -> dict: ...

    def list_for_user(self, user_id: str, limit: int) -> list[dict]:
        """The user's jobs, newest first."""
        ...

    def count_recent(self, client_hash: str, since: str, cap: int) -> int:
        """Jobs this client created since ``since`` (ISO time), counting at most ``cap``."""
        ...

    def expired(self, before: str, limit: int) -> list[dict]:
        """Up to ``limit`` jobs created before ``before`` (ISO time), oldest first."""
        ...

    def delete(self, jobs: list[dict]) -> None:
        """Remove the jobs and their uploaded and converted files."""
        ...

    def get(self, job_id: str) -> dict: ...

    def update(self, job_id: str, **fields) -> dict: ...

    def claim(self, job_id: str) -> dict | None:
        """Atomically move an uploaded job to ``processing``; None if it can't be claimed."""
        ...

    def upload_target(self, job: dict) -> dict:
        """Where the client sends the file: {"method", "url", "headers"}.

        A url starting with "/" is relative to the API base URL.
        """
        ...

    def read_input(self, job: dict) -> bytes: ...

    def write_output(self, job: dict, name: str, data: bytes, media_type: str) -> str: ...

    def output_url(self, job: dict) -> str | None:
        """Short-lived download URL, or None if the API must stream the file itself."""
        ...


INPUT_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}


def _input_path(job_id: str, filename: str) -> str:
    return f"{job_id}/{filename}"


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, job_id: str) -> Path:
        try:
            uuid.UUID(job_id)
        except ValueError:
            raise JobNotFound(job_id) from None
        return self.root / "jobs" / job_id

    def _save(self, job: dict) -> dict:
        (self._dir(job["id"]) / "job.json").write_text(json.dumps(job, indent=2))
        return job

    def create(
        self, filename: str, requested_format: str, client_hash: str | None = None, user_id: str | None = None
    ) -> dict:
        job_id = str(uuid.uuid4())
        self._dir(job_id).mkdir(parents=True)
        return self._save(
            {
                "id": job_id,
                "status": "awaiting_upload",
                "filename": filename,
                "requested_format": requested_format,
                "input_path": _input_path(job_id, filename),
                "client_hash": client_hash,
                "user_id": user_id,
                "created_at": now(),
            }
        )

    def _all(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in (self.root / "jobs").glob("*/job.json")]

    def list_for_user(self, user_id: str, limit: int) -> list[dict]:
        mine = [j for j in self._all() if j.get("user_id") == user_id]
        return sorted(mine, key=lambda j: j["created_at"], reverse=True)[:limit]

    def count_recent(self, client_hash: str, since: str, cap: int) -> int:
        return min(cap, sum(1 for j in self._all() if j.get("client_hash") == client_hash and j["created_at"] >= since))

    def expired(self, before: str, limit: int) -> list[dict]:
        return sorted((j for j in self._all() if j["created_at"] < before), key=lambda j: j["created_at"])[:limit]

    def delete(self, jobs: list[dict]) -> None:
        for job in jobs:
            shutil.rmtree(self._dir(job["id"]), ignore_errors=True)

    def get(self, job_id: str) -> dict:
        path = self._dir(job_id) / "job.json"
        if not path.exists():
            raise JobNotFound(job_id)
        return json.loads(path.read_text())

    def update(self, job_id: str, **fields) -> dict:
        job = self.get(job_id)
        job.update(fields)
        return self._save(job)

    def claim(self, job_id: str) -> dict | None:
        job = self.get(job_id)
        if job["status"] != "awaiting_upload" or not (self.root / "jobs" / job["input_path"]).exists():
            return None
        return self.update(job_id, status="processing")

    def save_upload(self, job_id: str, data: bytes) -> None:
        job = self.get(job_id)
        if job["status"] != "awaiting_upload":
            raise InputMissing("Upload is closed for this job")
        (self.root / "jobs" / job["input_path"]).write_bytes(data)

    def upload_target(self, job: dict) -> dict:
        return {"method": "PUT", "url": f"/v1/conversions/{job['id']}/upload", "headers": {}}

    def read_input(self, job: dict) -> bytes:
        path = self.root / "jobs" / job["input_path"]
        if not path.exists():
            raise InputMissing("File has not been uploaded")
        return path.read_bytes()

    def write_output(self, job: dict, name: str, data: bytes, media_type: str) -> str:
        path = f"{job['id']}/{name}"
        (self.root / "jobs" / path).write_bytes(data)
        return path

    def output_url(self, job: dict) -> str | None:
        return None

    def output_file(self, job: dict) -> Path:
        return self.root / "jobs" / job["output_path"]


class SupabaseStore:
    """Talks to Supabase's REST endpoints with the project's secret key.

    The secret key (``sb_secret_...``, or the legacy service_role JWT) bypasses
    row-level security, so it must only ever live on the server.
    """

    TABLE = "conversions"

    def __init__(self, url: str, key: str, input_bucket: str, output_bucket: str, client: httpx.Client | None = None):
        self.base = url.rstrip("/")
        self.input_bucket = input_bucket
        self.output_bucket = output_bucket
        self.http = client or httpx.Client(timeout=60)
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    # -- database (PostgREST) -------------------------------------------------

    def _rest(self, method: str, query: str = "", **kw) -> list[dict]:
        headers = {**self.headers, "Prefer": "return=representation", **kw.pop("headers", {})}
        r = self.http.request(method, f"{self.base}/rest/v1/{self.TABLE}{query}", headers=headers, **kw)
        r.raise_for_status()
        return r.json() if r.content else []

    @staticmethod
    def _check_id(job_id: str) -> None:
        try:
            uuid.UUID(job_id)
        except ValueError:
            raise JobNotFound(job_id) from None

    def create(
        self, filename: str, requested_format: str, client_hash: str | None = None, user_id: str | None = None
    ) -> dict:
        job_id = str(uuid.uuid4())
        rows = self._rest(
            "POST",
            json={
                "id": job_id,
                "status": "awaiting_upload",
                "filename": filename,
                "requested_format": requested_format,
                "input_path": _input_path(job_id, filename),
                "client_hash": client_hash,
                "user_id": user_id,
            },
        )
        return rows[0]

    def list_for_user(self, user_id: str, limit: int) -> list[dict]:
        params = {"user_id": f"eq.{user_id}", "select": "*", "order": "created_at.desc", "limit": str(limit)}
        return self._rest("GET", params=params)

    def count_recent(self, client_hash: str, since: str, cap: int) -> int:
        params = {"client_hash": f"eq.{client_hash}", "created_at": f"gte.{since}", "select": "id", "limit": str(cap)}
        return len(self._rest("GET", params=params))

    def expired(self, before: str, limit: int) -> list[dict]:
        params = {
            "created_at": f"lt.{before}",
            "select": "id,input_path,output_path",
            "order": "created_at.asc",
            "limit": str(limit),
        }
        return self._rest("GET", params=params)

    def delete(self, jobs: list[dict]) -> None:
        if not jobs:
            return
        # Files first: a row without files is harmless, files without a row are orphans.
        for bucket, key in ((self.input_bucket, "input_path"), (self.output_bucket, "output_path")):
            paths = [j[key] for j in jobs if j.get(key)]
            if paths:
                r = self.http.request(
                    "DELETE", f"{self.base}/storage/v1/object/{bucket}", headers=self.headers, json={"prefixes": paths}
                )
                r.raise_for_status()
        self._rest("DELETE", params={"id": f"in.({','.join(j['id'] for j in jobs)})"})

    def get(self, job_id: str) -> dict:
        self._check_id(job_id)
        rows = self._rest("GET", f"?id=eq.{job_id}&select=*")
        if not rows:
            raise JobNotFound(job_id)
        return rows[0]

    def update(self, job_id: str, **fields) -> dict:
        self._check_id(job_id)
        rows = self._rest("PATCH", f"?id=eq.{job_id}", json=fields)
        if not rows:
            raise JobNotFound(job_id)
        return rows[0]

    def claim(self, job_id: str) -> dict | None:
        self._check_id(job_id)
        # Conditional update: only one request can move the job out of awaiting_upload.
        rows = self._rest("PATCH", f"?id=eq.{job_id}&status=eq.awaiting_upload", json={"status": "processing"})
        return rows[0] if rows else None

    # -- storage ----------------------------------------------------------------

    def _object(self, bucket: str, path: str) -> str:
        return f"{bucket}/{quote(path)}"

    def upload_target(self, job: dict) -> dict:
        r = self.http.post(
            f"{self.base}/storage/v1/object/upload/sign/{self._object(self.input_bucket, job['input_path'])}",
            headers=self.headers,
        )
        r.raise_for_status()
        # The uploads bucket only accepts these types, and browsers don't always send one.
        content_type = INPUT_MEDIA_TYPES[Path(job["filename"]).suffix.lower()]
        return {
            "method": "PUT",
            "url": f"{self.base}/storage/v1{r.json()['url']}",
            "headers": {"Content-Type": content_type},
        }

    def read_input(self, job: dict) -> bytes:
        r = self.http.get(
            f"{self.base}/storage/v1/object/{self._object(self.input_bucket, job['input_path'])}",
            headers=self.headers,
        )
        if r.status_code in (400, 404):
            raise InputMissing("File has not been uploaded")
        r.raise_for_status()
        return r.content

    def write_output(self, job: dict, name: str, data: bytes, media_type: str) -> str:
        path = f"{job['id']}/{name}"
        r = self.http.post(
            f"{self.base}/storage/v1/object/{self._object(self.output_bucket, path)}",
            headers={**self.headers, "Content-Type": media_type, "x-upsert": "true"},
            content=data,
        )
        r.raise_for_status()
        return path

    def output_url(self, job: dict) -> str | None:
        r = self.http.post(
            f"{self.base}/storage/v1/object/sign/{self._object(self.output_bucket, job['output_path'])}",
            headers=self.headers,
            json={"expiresIn": 300},
        )
        r.raise_for_status()
        signed = r.json()["signedURL"]
        sep = "&" if "?" in signed else "?"
        return f"{self.base}/storage/v1{signed}{sep}download={quote(job['output_file'])}"


def make_store(settings: Settings) -> Store:
    if settings.supabase_url and settings.supabase_secret_key:
        return SupabaseStore(
            settings.supabase_url,
            settings.supabase_secret_key,
            settings.supabase_input_bucket,
            settings.supabase_output_bucket,
        )
    return LocalStore(settings.storage_dir)
