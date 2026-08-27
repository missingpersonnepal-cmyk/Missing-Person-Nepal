from __future__ import annotations

from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MissingPerson
from .normalization import normalize_phone, normalize_text


def _similarity(a: str | None, b: str | None) -> float:
    a_n, b_n = normalize_text(a), normalize_text(b)
    if not a_n or not b_n:
        return 0.0
    return SequenceMatcher(None, a_n, b_n).ratio()


def score_candidate(*, name: str | None, location: str | None, age: int | None, phone: str | None, person: MissingPerson) -> float:
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

    return round((name_score * 0.55 + location_score * 0.25 + age_score * 0.05 + phone_score * 0.15) * 100, 1)


def find_duplicates(db: Session, *, disaster_id: int, name: str | None, location: str | None, age: int | None, phone: str | None, limit: int = 5) -> list[tuple[MissingPerson, float]]:
    people = db.scalars(
        select(MissingPerson).where(
            MissingPerson.disaster_id == disaster_id,
            MissingPerson.archived.is_(False),
        )
    ).all()
    scored = [(person, score_candidate(name=name, location=location, age=age, phone=phone, person=person)) for person in people]
    scored = [item for item in scored if item[1] >= 45.0]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]
