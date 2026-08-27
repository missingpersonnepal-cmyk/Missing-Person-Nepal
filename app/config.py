from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./missing_person_dev.db")
    session_secret: str = os.getenv("SESSION_SECRET", "local-dev-only-change-me")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    app_env: str = os.getenv("APP_ENV", "development")
    auto_create_tables: bool = _as_bool(os.getenv("AUTO_CREATE_TABLES"), True)
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    cookie_secure: bool = _as_bool(os.getenv("COOKIE_SECURE"), False)
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "uploads"))
    export_dir: Path = Path(os.getenv("EXPORT_DIR", "exports"))
    discovery_max_queries_per_run: int = int(os.getenv("DISCOVERY_MAX_QUERIES_PER_RUN", "12"))
    discovery_results_per_query: int = int(os.getenv("DISCOVERY_RESULTS_PER_QUERY", "8"))
    discovery_request_delay_seconds: float = float(os.getenv("DISCOVERY_REQUEST_DELAY_SECONDS", "1.0"))
    discovery_timeout_seconds: float = float(os.getenv("DISCOVERY_TIMEOUT_SECONDS", "15"))


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.export_dir.mkdir(parents=True, exist_ok=True)
