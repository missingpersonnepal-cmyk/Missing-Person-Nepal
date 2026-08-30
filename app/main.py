from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.sessions import SessionMiddleware

from .api import router as api_router
from .config import settings
from .database import Base, SessionLocal, engine
from .models import AdminUser
from .routes.admin import router as admin_router
from .routes.public import router as public_router
from .security import hash_password

BASE_DIR = Path(__file__).resolve().parent


def seed_admin() -> None:
    if not settings.admin_password:
        return
    with SessionLocal() as db:
        existing = db.scalar(select(AdminUser).where(AdminUser.username == settings.admin_username))
        if existing is None:
            db.add(
                AdminUser(
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                    display_name=settings.admin_username,
                    role="super_admin",
                )
            )
            db.commit()


def check_database_ready() -> tuple[bool, str | None]:
    try:
        with SessionLocal() as db:
            db.execute(text("select 1"))
        return True, None
    except SQLAlchemyError as exc:
        return False, str(exc.__cause__ or exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_tables:
        Base.metadata.create_all(engine)
    seed_admin()
    yield


app = FastAPI(title="Nepal Disaster Missing Persons Hub", version="0.1.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax", https_only=settings.cookie_secure)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(api_router)
app.include_router(public_router)
app.include_router(admin_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    db_ok, error = check_database_ready()
    if not db_ok:
        return {"status": "degraded", "database": "down", "error": error or "unknown"}
    return {"status": "ok", "database": "up"}
