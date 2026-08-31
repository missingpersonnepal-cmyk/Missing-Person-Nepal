from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import SessionLocal
from ..models import Disaster, MissingPerson, PersonCaseState, Submission
from ..services.geo import parse_coords, geocode
from ..services.files import save_image
from ..services.normalization import canonicalize_url
from .common import parse_date, parse_int, parse_time, render

router = APIRouter()


def _geo_point_for_text(text: str):
    point = parse_coords(text)
    return point or geocode(text)


@router.get("/media/person/{case_number}")
def public_person_photo(case_number: str):
    """Serve only photos belonging to currently published, non-archived cases."""
    with SessionLocal() as db:
        person = db.scalar(
            select(MissingPerson).where(
                MissingPerson.case_number == case_number,
                MissingPerson.published.is_(True),
                MissingPerson.archived.is_(False),
            )
        )
        if person is None or not person.photo_path:
            return HTMLResponse("Not found", status_code=404)
        filename = person.photo_path
        if Path(filename).name != filename:
            return HTMLResponse("Not found", status_code=404)
        path = settings.upload_dir / filename
        if not path.is_file():
            return HTMLResponse("Not found", status_code=404)
        return FileResponse(path)


@router.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", disaster_id: int | None = None):
    with SessionLocal() as db:
        disasters = list(db.scalars(select(Disaster).order_by(Disaster.active.desc(), Disaster.start_date.desc())).all())
        if disaster_id is None and disasters:
            active = next((d for d in disasters if d.active), disasters[0])
            disaster_id = active.id
        stmt = (
            select(MissingPerson)
            .options(selectinload(MissingPerson.sources))
            .outerjoin(PersonCaseState, PersonCaseState.person_id == MissingPerson.id)
            .where(
                MissingPerson.published.is_(True),
                MissingPerson.archived.is_(False),
                func.coalesce(PersonCaseState.status, "missing") == "missing",
            )
            .order_by(MissingPerson.created_at.desc())
        )
        if disaster_id:
            stmt = stmt.where(MissingPerson.disaster_id == disaster_id)
        if q.strip():
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    MissingPerson.name.ilike(pattern),
                    MissingPerson.name_ne.ilike(pattern),
                    MissingPerson.case_number.ilike(pattern),
                    MissingPerson.last_seen_location.ilike(pattern),
                )
            )
        people = list(db.scalars(stmt.limit(250)).all())
        return render(
            request,
            "index.html",
            disasters=disasters,
            selected_disaster=disaster_id,
            people=people,
            q=q,
        )


@router.get("/person/{case_number}", response_class=HTMLResponse)
def person_detail(request: Request, case_number: str):
    with SessionLocal() as db:
        person = db.scalar(
            select(MissingPerson)
            .options(selectinload(MissingPerson.sources))
            .where(
                MissingPerson.case_number == case_number,
                MissingPerson.published.is_(True),
                MissingPerson.archived.is_(False),
            )
        )
        if person is None:
            return HTMLResponse("Not found", status_code=404)
        return render(request, "person.html", person=person)


@router.get("/report", response_class=HTMLResponse)
def report_form(request: Request):
    with SessionLocal() as db:
        disasters = list(
            db.scalars(select(Disaster).where(Disaster.active.is_(True)).order_by(Disaster.start_date.desc())).all()
        )
        return render(request, "report.html", disasters=disasters, error=None, success=None)


@router.post("/report", response_class=HTMLResponse)
async def submit_report(request: Request):
    form = await request.form()
    with SessionLocal() as db:
        disasters = list(
            db.scalars(select(Disaster).where(Disaster.active.is_(True)).order_by(Disaster.start_date.desc())).all()
        )
        disaster_id = parse_int(form.get("disaster_id"))
        selected_disaster = db.get(Disaster, disaster_id) if disaster_id is not None else None
        if selected_disaster is None or not selected_disaster.active:
            return render(
                request,
                "report.html",
                disasters=disasters,
                error="Please select an active disaster.",
                success=None,
            )
        name = str(form.get("name") or "").strip()
        last_seen_location = str(form.get("last_seen_location") or "").strip()
        if not name or not last_seen_location:
            return render(
                request,
                "report.html",
                disasters=disasters,
                error="Name and last-seen location are required.",
                success=None,
            )
        try:
            photo_path = await save_image(form.get("photo"), settings.upload_dir)
        except ValueError as exc:
            return render(request, "report.html", disasters=disasters, error=str(exc), success=None)
        selected_point = parse_coords(
            f"{form.get('last_seen_lat') or ''},{form.get('last_seen_lon') or ''}"
        )
        point = selected_point or _geo_point_for_text(last_seen_location)

        social_url = canonicalize_url(str(form.get("social_url") or "")) or None
        submission = Submission(
            disaster_id=disaster_id,
            kind="missing_report",
            name=name,
            name_ne=str(form.get("name_ne") or "").strip() or None,
            age=parse_int(form.get("age")),
            gender=str(form.get("gender") or "").strip() or None,
            photo_path=photo_path,
            residential_address_private=str(form.get("residential_address") or "").strip() or None,
            last_seen_date=parse_date(form.get("last_seen_date")),
            last_seen_time=parse_time(form.get("last_seen_time")),
            last_seen_location=last_seen_location,
            last_seen_lat=point.lat if point else None,
            last_seen_lon=point.lon if point else None,
            clothing=str(form.get("clothing") or "").strip() or None,
            identification_details=str(form.get("identification_details") or "").strip() or None,
            public_contact_number=str(form.get("public_contact_number") or "").strip() or None,
            reporter_name_private=str(form.get("reporter_name") or "").strip() or None,
            reporter_phone_private=str(form.get("reporter_phone") or "").strip() or None,
            reporter_relationship=str(form.get("reporter_relationship") or "").strip() or None,
            social_url=social_url,
            notes=str(form.get("notes") or "").strip() or None,
        )
        db.add(submission)
        db.commit()
        return render(
            request,
            "report.html",
            disasters=disasters,
            error=None,
            success=f"Report received. Reference SUB-{submission.id:06d}. It will be reviewed before publication.",
        )


@router.get("/person/{case_number}/information", response_class=HTMLResponse)
def info_form(request: Request, case_number: str):
    with SessionLocal() as db:
        person = db.scalar(
            select(MissingPerson).where(
                MissingPerson.case_number == case_number,
                MissingPerson.published.is_(True),
            )
        )
        if person is None:
            return HTMLResponse("Not found", status_code=404)
        return render(request, "information.html", person=person, success=None)


@router.post("/person/{case_number}/information", response_class=HTMLResponse)
async def info_submit(request: Request, case_number: str):
    form = await request.form()
    with SessionLocal() as db:
        person = db.scalar(
            select(MissingPerson).where(
                MissingPerson.case_number == case_number,
                MissingPerson.published.is_(True),
            )
        )
        if person is None:
            return HTMLResponse("Not found", status_code=404)
        text = str(form.get("notes") or "").strip()
        source_url = canonicalize_url(str(form.get("social_url") or "")) or None
        if not text and not source_url:
            return render(request, "information.html", person=person, success="Please provide information or a source URL.")
        db.add(
            Submission(
                disaster_id=person.disaster_id,
                person_id=person.id,
                kind="additional_info",
                status="pending",
                name=person.name,
                social_url=source_url,
                notes=text or None,
                reporter_name_private=str(form.get("reporter_name") or "").strip() or None,
                reporter_phone_private=str(form.get("reporter_phone") or "").strip() or None,
            )
        )
        db.commit()
        return render(request, "information.html", person=person, success="Information submitted for admin review.")
