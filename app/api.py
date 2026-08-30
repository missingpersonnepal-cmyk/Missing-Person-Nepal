from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from .database import SessionLocal
from .models import Disaster, MissingPerson, PersonCaseState

router = APIRouter(prefix="/api/v1", tags=["public"])


def person_payload(person: MissingPerson, include_sources: bool = False) -> dict:
    payload = {
        "case_number": person.case_number,
        "disaster_id": person.disaster_id,
        "name": person.name,
        "name_ne": person.name_ne,
        "age": person.age,
        "gender": person.gender,
        "photo_url": f"/media/person/{person.case_number}" if person.photo_path else None,
        "last_seen_date": person.last_seen_date.isoformat() if person.last_seen_date else None,
        "last_seen_time": person.last_seen_time.isoformat(timespec="minutes") if person.last_seen_time else None,
        "last_seen_location": person.last_seen_location,
        "clothing": person.clothing,
        "identification_details": person.identification_details,
        "public_contact_number": person.public_contact_number,
        "updated_at": person.updated_at.isoformat() if person.updated_at else None,
    }
    if include_sources:
        payload["sources"] = [
            {
                "platform": source.platform,
                "url": source.url,
                "source_name": source.source_name,
                "discovered_at": source.discovered_at.isoformat() if source.discovered_at else None,
            }
            for source in person.sources
        ]
    return payload


@router.get("/events")
def events():
    with SessionLocal() as db:
        rows = db.scalars(select(Disaster).order_by(Disaster.start_date.desc())).all()
        return [
            {
                "id": d.id,
                "code": d.code,
                "name": d.name,
                "disaster_type": d.disaster_type,
                "start_date": d.start_date.isoformat(),
                "affected_locations": d.locations(),
                "active": d.active,
            }
            for d in rows
        ]


@router.get("/people")
def people(
    disaster_id: int | None = None,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=100, ge=1, le=250),
):
    with SessionLocal() as db:
        stmt = (
            select(MissingPerson)
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
                    MissingPerson.last_seen_location.ilike(pattern),
                )
            )
        return [person_payload(p) for p in db.scalars(stmt.limit(limit)).all()]


@router.get("/people/{case_number}")
def person(case_number: str):
    with SessionLocal() as db:
        row = db.scalar(
            select(MissingPerson)
            .options(selectinload(MissingPerson.sources))
            .where(
                MissingPerson.case_number == case_number,
                MissingPerson.published.is_(True),
                MissingPerson.archived.is_(False),
            )
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Case not found")
        return person_payload(row, include_sources=True)
