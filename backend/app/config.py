from pathlib import Path

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

    # Supabase (production). When url and secret key are both set, jobs go to
    # Postgres and files to Storage; otherwise everything stays in storage_dir.
    supabase_url: str | None = None
    supabase_secret_key: str | None = None
    supabase_input_bucket: str = "uploads"
    supabase_output_bucket: str = "outputs"
    storage_dir: Path = Path("./storage")


settings = Settings()
