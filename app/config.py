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
    database_url: str = os.getenv("DATABASE_URL", "")
    session_secret: str = os.getenv("SESSION_SECRET", "local-dev-only-change-me")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    app_env: str = os.getenv("APP_ENV", "development")
    auto_create_tables: bool = _as_bool(os.getenv("AUTO_CREATE_TABLES"), True)
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    cookie_secure: bool = _as_bool(os.getenv("COOKIE_SECURE"), False)
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "uploads"))
    export_dir: Path = Path(os.getenv("EXPORT_DIR", "exports"))
    discovery_max_queries_per_run: int = int(os.getenv("DISCOVERY_MAX_QUERIES_PER_RUN", "24"))
    discovery_results_per_query: int = int(os.getenv("DISCOVERY_RESULTS_PER_QUERY", "10"))
    discovery_request_delay_seconds: float = float(os.getenv("DISCOVERY_REQUEST_DELAY_SECONDS", "1.0"))
    discovery_timeout_seconds: float = float(os.getenv("DISCOVERY_TIMEOUT_SECONDS", "15"))
    sms_provider: str = os.getenv("SMS_PROVIDER", "disabled").strip().casefold()
    email_provider: str = os.getenv("EMAIL_PROVIDER", "disabled").strip().casefold()
    sms_from: str = os.getenv("SMS_FROM", "")
    email_from: str = os.getenv("EMAIL_FROM", "")
    geo_api_base_url: str = os.getenv("GEO_API_BASE_URL", "https://merogeo.com").rstrip("/")
    geo_api_key: str = os.getenv("GEO_API_KEY", "")
    port: int = int(os.getenv("PORT", "8000"))


settings = Settings()

if settings.app_env.strip().casefold() == "production" and not settings.database_url.strip():
    raise RuntimeError("DATABASE_URL is required when APP_ENV=production")

settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.export_dir.mkdir(parents=True, exist_ok=True)
