from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MKUNGI_", env_file=".env")

    # rapidocr runs PaddleOCR's models on ONNX Runtime and fits in a Vercel
    # function; "paddleocr" (GPU servers) and "tesseract" are alternatives.
    ocr_engine: str = "rapidocr"
    ocr_lang: str = "en"
    max_upload_mb: int = 25
    max_pages: int = 20
    cors_origins: list[str] = ["http://localhost:3000"]
    # Matches Vercel preview deployments of the web app, e.g. https://mkungi-web-git-x-team.vercel.app
    cors_origin_regex: str | None = None

    # Abuse limit: conversions each visitor (hashed IP) may start per hour; 0 turns it off.
    max_conversions_per_hour: int = 30
    ip_hash_salt: str = "mkungi"

    # Retention: jobs and their files are deleted this long after creation by
    # /v1/maintenance/cleanup, which Vercel Cron calls daily (vercel.json).
    retention_hours: int = 24
    # Vercel sends "Authorization: Bearer $CRON_SECRET" on cron requests.
    cron_secret: str | None = Field(None, validation_alias=AliasChoices("MKUNGI_CRON_SECRET", "CRON_SECRET"))

    # Supabase (production). When url and secret key are both set, jobs go to
    # Postgres and files to Storage; otherwise everything stays in storage_dir.
    supabase_url: str | None = None
    supabase_secret_key: str | None = None
    supabase_input_bucket: str = "uploads"
    supabase_output_bucket: str = "outputs"
    storage_dir: Path = Path("./storage")

    # Sign-in. None means "required whenever Supabase is configured", so
    # local development without Supabase keeps working without accounts.
    require_auth: bool | None = None

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_secret_key)

    @property
    def auth_required(self) -> bool:
        return self.supabase_enabled if self.require_auth is None else self.require_auth


settings = Settings()
