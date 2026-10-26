"""Runtime configuration loaded from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/


def _load_dotenv() -> None:
    """Minimal .env loader so the prototype runs without python-dotenv."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://aicte:aicte_dev@localhost:5432/aicte_verify"
    )
    secret_key: str = os.getenv("SECRET_KEY", "")
    token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "480"))
    cookie_secure: bool = _bool("COOKIE_SECURE", False)
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if o.strip()
        ]
    )
    storage_dir: Path = Path(os.getenv("STORAGE_DIR", str(BASE_DIR.parent / "storage")))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "15"))
    # live | simulated | disabled
    crossref_mode: str = os.getenv("CROSSREF_MODE", "live")
    crossref_mailto: str = os.getenv("CROSSREF_MAILTO", "")
    crossref_timeout: float = float(os.getenv("CROSSREF_TIMEOUT_SECONDS", "8"))
    scopus_api_key: str = os.getenv("SCOPUS_API_KEY", "")
    scopus_insttoken: str = os.getenv("SCOPUS_INSTTOKEN", "")
    # sync = run verification inline (tests), thread = background worker thread
    jobs_mode: str = os.getenv("JOBS_MODE", "thread")
    tesseract_cmd: str = os.getenv("TESSERACT_CMD", "")
    login_rate_limit_per_minute: int = int(os.getenv("LOGIN_RATE_LIMIT_PER_MINUTE", "10"))
    # Reference date for expiry checks; empty = today
    expiry_reference_date: str = os.getenv("EXPIRY_REFERENCE_DATE", "")


settings = Settings()

if not settings.secret_key:
    if settings.env == "production":
        raise RuntimeError("SECRET_KEY must be set in production")
    # Development-only fallback; a warning is logged at startup.
    object.__setattr__(settings, "secret_key", "dev-only-insecure-key-change-me-0123456789abcdef")

settings.storage_dir.mkdir(parents=True, exist_ok=True)
