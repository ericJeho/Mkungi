"""Mkungi API.

Jobs are stored on disk for the MVP (``storage_dir/jobs/<id>/``). Phase 2 of
docs/BUILD_CHECKLIST.md moves job state to PostgreSQL and the work to a
Redis-backed worker; the endpoints stay the same.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.pipeline.ocr import OCREngine, get_engine
from app.pipeline.run import FORMATS, MEDIA_TYPES, convert

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".pdf"}

app = FastAPI(title="Mkungi API", version="0.1.0", description="From Paper to Perfectly Editable.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache
def ocr_engine() -> OCREngine:
    return get_engine(settings.ocr_engine, settings.ocr_lang)


def _job_dir(job_id: str) -> Path:
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(404, "Job not found") from None
    return settings.storage_dir / "jobs" / job_id


def _save_meta(job_dir: Path, meta: dict) -> None:
    (job_dir / "job.json").write_text(json.dumps(meta, indent=2))


def _load_meta(job_id: str) -> dict:
    path = _job_dir(job_id) / "job.json"
    if not path.exists():
        raise HTTPException(404, "Job not found")
    return json.loads(path.read_text())


def _process(job_dir: Path, data: bytes, filename: str, output_format: str, engine: OCREngine) -> None:
    meta = json.loads((job_dir / "job.json").read_text())
    meta["status"] = "processing"
    _save_meta(job_dir, meta)
    try:
        result = convert(data, filename, output_format, engine)
        out_name = f"{Path(filename).stem}.{result.output_format}"
        (job_dir / out_name).write_bytes(result.data)
        meta.update(
            status="done",
            output_format=result.output_format,
            output_file=out_name,
            doc_type=result.layout.doc_type,
            pages=len(result.layout.pages),
            tables=sum(len(p.tables) for p in result.layout.pages),
            images=sum(len(p.images) for p in result.layout.pages),
        )
    except Exception as exc:  # surfaced to the client via job status
        meta.update(status="failed", error=str(exc))
    meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    _save_meta(job_dir, meta)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "ocr_engine": settings.ocr_engine}


@app.post("/v1/conversions", status_code=202)
async def create_conversion(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    output_format: str = Form("auto"),
    engine: OCREngine = Depends(ocr_engine),
) -> dict:
    filename = Path(file.filename or "upload").name
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(415, f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}")
    if output_format not in FORMATS:
        raise HTTPException(422, f"output_format must be one of {sorted(FORMATS)}")
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")

    job_id = str(uuid.uuid4())
    job_dir = _job_dir(job_id)
    job_dir.mkdir(parents=True)
    meta = {
        "id": job_id,
        "status": "queued",
        "filename": filename,
        "requested_format": output_format,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_meta(job_dir, meta)
    background.add_task(_process, job_dir, data, filename, output_format, engine)
    return meta


@app.get("/v1/conversions/{job_id}")
def get_conversion(job_id: str) -> dict:
    return _load_meta(job_id)


@app.get("/v1/conversions/{job_id}/download")
def download(job_id: str) -> FileResponse:
    meta = _load_meta(job_id)
    if meta["status"] != "done":
        raise HTTPException(409, f"Job is {meta['status']}")
    return FileResponse(
        _job_dir(job_id) / meta["output_file"],
        media_type=MEDIA_TYPES[meta["output_format"]],
        filename=meta["output_file"],
    )
