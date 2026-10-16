from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MKUNGI_", env_file=".env")

    ocr_engine: str = "paddleocr"  # or "tesseract"
    ocr_lang: str = "en"
    storage_dir: Path = Path("./storage")
    max_upload_mb: int = 25
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
