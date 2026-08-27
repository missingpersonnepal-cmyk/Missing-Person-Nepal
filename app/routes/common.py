from __future__ import annotations

from datetime import date, time
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AuditLog, Disaster, MissingPerson

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


def admin_gate(request: Request) -> RedirectResponse | None:
    if not admin_username(request):
        return RedirectResponse("/admin/login", status_code=303)
    return None


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
    return TEMPLATES.TemplateResponse(request=request, name=template, context=context)
