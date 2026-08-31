from __future__ import annotations

from collections.abc import Generator
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


def _normalize_database_url(database_url: str) -> str:
    raw = database_url.strip()
    if raw.startswith(("sqlite://", "postgresql+psycopg://")):
        return raw
    if raw.startswith(("postgresql://", "postgres://")):
        parts = urlsplit(raw)
        return urlunsplit(("postgresql+psycopg", parts.netloc, parts.path, parts.query, parts.fragment))
    return raw


database_url = _normalize_database_url(settings.database_url)
if settings.app_env.strip().casefold() == "production" and database_url.startswith("sqlite"):
    raise RuntimeError("DATABASE_URL must point to PostgreSQL when APP_ENV=production")
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
database_url = engine.url.render_as_string(hide_password=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
