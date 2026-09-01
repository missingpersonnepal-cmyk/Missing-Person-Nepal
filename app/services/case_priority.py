from __future__ import annotations

from datetime import date


def case_priority(person, *, today: date | None = None) -> tuple[int, str]:
    """Return a transparent urgency score and label for operator triage."""
    today = today or date.today()
    score = 0
    if person.age is not None and (person.age < 13 or person.age >= 65):
        score += 40
    if person.last_seen_date:
        age_days = max((today - person.last_seen_date).days, 0)
        score += max(0, 30 - min(age_days, 30))
    if person.location_uncertain:
        score += 10
    if not person.source_confirmed:
        score += 8
    if person.published:
        score += 4
    if person.last_seen_lat is not None and person.last_seen_lon is not None:
        score += 8
    label = "Urgent" if score >= 60 else "High" if score >= 40 else "Standard"
    return score, label
