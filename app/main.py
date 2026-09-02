from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
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


@app.middleware("http")
async def browser_security(request: Request, call_next):
    """Apply baseline browser protections without blocking the local map assets."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/admin/"):
        origin = request.headers.get("origin")
        if origin:
            origin_host = urlsplit(origin).netloc.casefold()
            request_host = request.headers.get("host", "").casefold()
            if not origin_host or origin_host != request_host:
                return Response("Forbidden", status_code=403)

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
        "object-src 'none'; connect-src 'self'; img-src 'self' data: https://*.openstreetmap.org "
        "https://*.openstreetmap.fr; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'",
    )
    return response
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(api_router)
app.include_router(public_router)
app.include_router(admin_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready():
    db_ok, error = check_database_ready()
    if not db_ok:
        # Connection details can reveal infrastructure information and must not
        # be returned by a public readiness endpoint.
        return JSONResponse({"status": "degraded", "database": "down"}, status_code=503)
    return {"status": "ok", "database": "up"}
