from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from .database import SessionLocal
from .models import Disaster, MissingPerson, PersonCaseState
from .services.geo import geocode, geocode_results

router = APIRouter(prefix="/api/v1", tags=["public"])


def person_payload(person: MissingPerson, include_sources: bool = False, case_status: str = "missing") -> dict:
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
        "last_seen_lat": person.last_seen_lat,
        "last_seen_lon": person.last_seen_lon,
        "clothing": person.clothing,
        "identification_details": person.identification_details,
        "public_contact_number": person.public_contact_number,
        "case_status": case_status,
        "created_at": person.created_at.isoformat() if person.created_at else None,
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
                "center_lat": d.center_lat,
                "center_lon": d.center_lon,
                "boundary_geojson": d.boundary_geojson,
                "active": d.active,
            }
            for d in rows
        ]


@router.get("/places")
def places(q: str = Query(..., min_length=2, max_length=120)):
    """Return safe place suggestions for location fields."""
    try:
        results = geocode_results(q)
    except Exception:
        results = []
    return [{"label": item.label or q, "lat": item.lat, "lon": item.lon} for item in results]


@router.get("/people")
def people(
    disaster_id: int | None = None,
    q: str = Query(default="", max_length=120),
    status: str = Query(default="missing", max_length=20),
    limit: int = Query(default=100, ge=1, le=250),
):
    with SessionLocal() as db:
        stmt = (
            select(MissingPerson)
            .outerjoin(PersonCaseState, PersonCaseState.person_id == MissingPerson.id)
            .where(MissingPerson.published.is_(True), MissingPerson.archived.is_(False))
            .order_by(MissingPerson.created_at.desc())
        )
        normalized_status = (status or "missing").strip().casefold()
        if normalized_status != "all":
            stmt = stmt.where(func.coalesce(PersonCaseState.status, "missing") == normalized_status)
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
        rows = db.scalars(stmt.limit(limit)).all()
        mutated = False
        for row in rows:
            if (
                row.last_seen_lat is None
                or row.last_seen_lon is None
            ) and row.last_seen_location:
                point = geocode(row.last_seen_location)
                if point:
                    row.last_seen_lat = point.lat
                    row.last_seen_lon = point.lon
                    mutated = True
        state_rows = db.scalars(select(PersonCaseState).where(PersonCaseState.person_id.in_([p.id for p in rows]))).all()
        state_map = {row.person_id: row.status for row in state_rows}
        if mutated:
            db.commit()
        return [person_payload(p, case_status=state_map.get(p.id, "missing")) for p in rows]


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
        state = db.get(PersonCaseState, row.id)
        return person_payload(row, include_sources=True, case_status=state.status if state else "missing")


@router.get("/nearby")
def nearby(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(default=5.0, ge=0.1, le=200.0),
):
    def haversine(a_lat, a_lon, b_lat, b_lon):
        from math import asin, cos, radians, sin, sqrt
        r = 6371.0
        dlat = radians(b_lat - a_lat)
        dlon = radians(b_lon - a_lon)
        sa = sin(dlat / 2) ** 2 + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlon / 2) ** 2
        return 2 * r * asin(sqrt(sa))

    with SessionLocal() as db:
        rows = db.scalars(
            select(MissingPerson).where(
                MissingPerson.published.is_(True),
                MissingPerson.archived.is_(False),
                MissingPerson.last_seen_lat.is_not(None),
                MissingPerson.last_seen_lon.is_not(None),
            )
        ).all()
        items = []
        for row in rows:
            distance = haversine(lat, lon, row.last_seen_lat, row.last_seen_lon)
            if distance <= radius_km:
                state = db.get(PersonCaseState, row.id)
                items.append({**person_payload(row, case_status=state.status if state else "missing"), "distance_km": round(distance, 2)})
        return sorted(items, key=lambda item: item["distance_km"])
