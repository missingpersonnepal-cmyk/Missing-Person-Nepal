from __future__ import annotations

from datetime import date, time
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import AdminUser, AuditLog, Disaster, MissingPerson

BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def parse_time(value: Any) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def admin_username(request: Request) -> str | None:
    value = request.session.get("admin")
    return str(value) if value else None


def current_admin(db: Session, request: Request) -> AdminUser | None:
    username = admin_username(request)
    if not username:
        return None
    return db.scalar(select(AdminUser).where(AdminUser.username == username, AdminUser.active.is_(True)))


def admin_gate(request: Request) -> RedirectResponse | None:
    username = admin_username(request)
    if not username:
        return RedirectResponse("/admin/login", status_code=303)
    with SessionLocal() as db:
        if current_admin(db, request) is None:
            request.session.clear()
            return RedirectResponse("/admin/login", status_code=303)
    return None


def role_gate(request: Request, allowed_roles: set[str]) -> HTMLResponse | RedirectResponse | None:
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        admin = current_admin(db, request)
        if admin is None or admin.role not in allowed_roles:
            return HTMLResponse("Forbidden", status_code=403)
    return None


def write_gate(request: Request) -> HTMLResponse | RedirectResponse | None:
    """Block read-only accounts from every admin mutation by default."""
    return role_gate(request, {"super_admin", "admin", "reviewer", "data_entry"})


def audit(
    db: Session,
    request: Request,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        AuditLog(
            admin_username=admin_username(request) or "system",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
        )
    )


def next_case_number(db: Session, disaster: Disaster) -> str:
    count = db.scalar(select(func.count(MissingPerson.id)).where(MissingPerson.disaster_id == disaster.id)) or 0
    while True:
        case = f"NP-{disaster.start_date.year}-{disaster.code.upper()}-{count + 1:05d}"
        exists = db.scalar(select(func.count(MissingPerson.id)).where(MissingPerson.case_number == case))
        if not exists:
            return case
        count += 1


def render(request: Request, template: str, **context: Any) -> HTMLResponse:
    context.setdefault("admin_username", admin_username(request))
    if "admin_role" not in context and admin_username(request):
        with SessionLocal() as db:
            admin = current_admin(db, request)
            context["admin_role"] = admin.role if admin else None
    return TEMPLATES.TemplateResponse(request=request, name=template, context=context)
