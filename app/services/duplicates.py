from __future__ import annotations

from difflib import SequenceMatcher
from datetime import date
from math import asin, cos, radians, sin, sqrt
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MissingPerson
from .normalization import normalize_phone, normalize_text


def _similarity(a: str | None, b: str | None) -> float:
    a_n, b_n = normalize_text(a), normalize_text(b)
    if not a_n or not b_n:
        return 0.0
    return SequenceMatcher(None, a_n, b_n).ratio()


def _image_fingerprint(path: str | None) -> str | None:
    match = re.search(r"-([0-9a-f]{16})\.[^.]+$", str(path or ""), re.I)
    return match.group(1).lower() if match else None


def score_candidate(*, name: str | None, location: str | None, age: int | None, phone: str | None, last_seen_date: date | None = None, lat: float | None = None, lon: float | None = None, photo_path: str | None = None, person: MissingPerson) -> float:
    name_score = _similarity(name, person.name)
    if person.name_ne:
        name_score = max(name_score, _similarity(name, person.name_ne))
    location_score = _similarity(location, person.last_seen_location)

    age_score = 0.0
    if age is not None and person.age is not None:
        diff = abs(age - person.age)
        age_score = 1.0 if diff == 0 else 0.6 if diff <= 2 else 0.0

    phone_score = 0.0
    normalized = normalize_phone(phone)
    if normalized:
        phone_score = 1.0 if normalized in {
            normalize_phone(person.public_contact_number),
            normalize_phone(person.private_contact_number),
        } else 0.0

    date_score = 0.0
    if last_seen_date and person.last_seen_date:
        days = abs((last_seen_date - person.last_seen_date).days)
        date_score = 1.0 if days == 0 else 0.8 if days <= 2 else 0.4 if days <= 7 else 0.0

    coordinate_score = 0.0
    if lat is not None and lon is not None and person.last_seen_lat is not None and person.last_seen_lon is not None:
        dlat = radians(person.last_seen_lat - lat)
        dlon = radians(person.last_seen_lon - lon)
        value = sin(dlat / 2) ** 2 + cos(radians(lat)) * cos(radians(person.last_seen_lat)) * sin(dlon / 2) ** 2
        km = 6371.0 * 2 * asin(sqrt(value))
        coordinate_score = 1.0 if km <= 1 else 0.8 if km <= 5 else 0.3 if km <= 20 else 0.0

    image_score = 1.0 if _image_fingerprint(photo_path) and _image_fingerprint(photo_path) == _image_fingerprint(person.photo_path) else 0.0

    return round((name_score * 0.45 + location_score * 0.18 + age_score * 0.07 + phone_score * 0.15 + date_score * 0.07 + coordinate_score * 0.03 + image_score * 0.05) * 100, 1)


def find_duplicates(db: Session, *, disaster_id: int | None, name: str | None, location: str | None, age: int | None, phone: str | None, last_seen_date: date | None = None, lat: float | None = None, lon: float | None = None, photo_path: str | None = None, limit: int = 5) -> list[tuple[MissingPerson, float]]:
    if disaster_id is None:
        return []
    people = db.scalars(
        select(MissingPerson).where(
            MissingPerson.disaster_id == disaster_id,
            MissingPerson.archived.is_(False),
        )
    ).all()
    scored = [(person, score_candidate(name=name, location=location, age=age, phone=phone, last_seen_date=last_seen_date, lat=lat, lon=lon, photo_path=photo_path, person=person)) for person in people]
    scored = [item for item in scored if item[1] >= 45.0]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]
