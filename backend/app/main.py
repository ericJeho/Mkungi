"""Mkungi API.

A conversion takes three calls, so large files never pass through the API
(Vercel functions accept at most 4.5 MB per request):

1. ``POST /v1/conversions``            create the job, get an upload target
2. ``PUT  <upload.url>``               send the file (straight to Supabase Storage in production)
3. ``POST /v1/conversions/{id}/process`` run the conversion and wait for the result

Then ``GET /v1/conversions/{id}/download`` returns the Word/Excel file.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from app.config import settings
from app.pipeline.ocr import OCREngine, get_engine
from app.pipeline.run import MEDIA_TYPES, convert
from app.storage import INPUT_MEDIA_TYPES, InputMissing, JobNotFound, LocalStore, Store, make_store, now

ALLOWED_SUFFIXES = set(INPUT_MEDIA_TYPES)

app = FastAPI(title="Mkungi API", version="0.2.0", description="From Paper to Perfectly Editable.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache
def ocr_engine() -> OCREngine:
    return get_engine(settings.ocr_engine, settings.ocr_lang)


@lru_cache
def store() -> Store:
    return make_store(settings)


def _get(s: Store, job_id: str) -> dict:
    try:
        return s.get(job_id)
    except JobNotFound:
        raise HTTPException(404, "Job not found") from None


def _public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k not in ("input_path", "output_path", "client_hash")}


def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def client_hash(request: Request) -> str:
    """A salted hash of the visitor's IP: enough to rate-limit, without storing the IP.

    On Vercel the edge sets x-real-ip itself, so it can't be spoofed by the client.
    Elsewhere the socket address is used (put a trusted proxy in front if needed).
    """
    ip = request.headers.get("x-real-ip") if os.getenv("VERCEL") else None
    ip = ip or (request.client.host if request.client else "unknown")
    return hashlib.sha256(f"{settings.ip_hash_salt}:{ip}".encode()).hexdigest()[:32]


class CreateConversion(BaseModel):
    filename: str
    output_format: Literal["auto", "docx", "xlsx"] = "auto"


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "ocr_engine": settings.ocr_engine,
        "storage": "supabase" if settings.supabase_url and settings.supabase_secret_key else "local",
    }


@app.post("/v1/conversions", status_code=201)
def create_conversion(body: CreateConversion, request: Request, s: Store = Depends(store)) -> dict:
    filename = Path(body.filename).name.strip()
    if not filename or Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(415, f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}")
    who = client_hash(request)
    limit = settings.max_conversions_per_hour
    if limit and s.count_recent(who, _ago(1), limit) >= limit:
        raise HTTPException(
            429,
            f"You've reached the limit of {limit} conversions per hour. Please try again later.",
            headers={"Retry-After": "3600"},
        )
    job = s.create(filename, body.output_format, who)
    return {
        **_public(job),
        "upload": s.upload_target(job),
        "max_upload_mb": settings.max_upload_mb,
        "retention_hours": settings.retention_hours,
    }


@app.put("/v1/conversions/{job_id}/upload", status_code=204)
async def upload(job_id: str, request: Request, s: Store = Depends(store)) -> None:
    """Upload endpoint for local storage. With Supabase, files go straight to Storage."""
    if not isinstance(s, LocalStore):
        raise HTTPException(404, "Upload directly to the URL returned when the job was created")
    _get(s, job_id)
    data = await request.body()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")
    try:
        s.save_upload(job_id, data)
    except InputMissing as exc:
        raise HTTPException(409, str(exc)) from None


@app.post("/v1/conversions/{job_id}/process")
def process(job_id: str, s: Store = Depends(store), engine: OCREngine = Depends(ocr_engine)) -> dict:
    job = _get(s, job_id)
    if job["status"] != "awaiting_upload":
        raise HTTPException(409, f"Job is already {job['status']}")
    try:
        data = s.read_input(job)
    except InputMissing as exc:
        raise HTTPException(409, str(exc)) from None
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        job = s.update(job_id, status="failed", error=f"File exceeds {settings.max_upload_mb} MB", finished_at=now())
        return _public(job)

    job = s.claim(job_id)
    if job is None:
        raise HTTPException(409, "Job is already being processed")

    try:
        result = convert(data, job["filename"], job["requested_format"], engine, settings.max_pages)
        out_name = f"{Path(job['filename']).stem}.{result.output_format}"
        out_path = s.write_output(job, out_name, result.data, MEDIA_TYPES[result.output_format])
        job = s.update(
            job_id,
            status="done",
            output_format=result.output_format,
            output_file=out_name,
            output_path=out_path,
            doc_type=result.layout.doc_type,
            pages=len(result.layout.pages),
            tables=sum(len(p.tables) for p in result.layout.pages),
            images=sum(len(p.images) for p in result.layout.pages),
            finished_at=now(),
        )
    except Exception as exc:  # reported to the client through the job
        job = s.update(job_id, status="failed", error=str(exc) or type(exc).__name__, finished_at=now())
    return _public(job)


@app.get("/v1/conversions/{job_id}")
def get_conversion(job_id: str, s: Store = Depends(store)) -> dict:
    return _public(_get(s, job_id))


@app.get("/v1/conversions/{job_id}/download", response_model=None)
def download(job_id: str, s: Store = Depends(store)) -> FileResponse | RedirectResponse:
    job = _get(s, job_id)
    if job["status"] != "done":
        raise HTTPException(409, f"Job is {job['status']}")
    url = s.output_url(job)
    if url:
        return RedirectResponse(url, status_code=307)
    assert isinstance(s, LocalStore)
    return FileResponse(
        s.output_file(job),
        media_type=MEDIA_TYPES[job["output_format"]],
        filename=job["output_file"],
    )


@app.get("/v1/maintenance/cleanup")
def cleanup(request: Request, s: Store = Depends(store)) -> dict:
    """Delete jobs and files past the retention period. Called daily by Vercel Cron."""
    expected = f"Bearer {settings.cron_secret}" if settings.cron_secret else None
    given = request.headers.get("authorization", "")
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "Unauthorized")
    before, deleted, started = _ago(settings.retention_hours), 0, time.monotonic()
    # Work in batches and stop well inside the function's time limit; the next run continues.
    while time.monotonic() - started < 120:
        batch = s.expired(before, 100)
        if not batch:
            break
        s.delete(batch)
        deleted += len(batch)
    return {"deleted": deleted, "before": before}
