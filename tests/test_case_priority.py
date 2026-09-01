from datetime import date, timedelta
from types import SimpleNamespace

from app.services.case_priority import case_priority


def person(**overrides):
    values = {
        "age": 30,
        "last_seen_date": date.today() - timedelta(days=10),
        "location_uncertain": False,
        "source_confirmed": True,
        "published": False,
        "last_seen_lat": 28.2,
        "last_seen_lon": 84.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_priority_puts_children_and_recent_reports_first():
    urgent = case_priority(person(age=8, last_seen_date=date.today()))
    ordinary = case_priority(person(age=30, last_seen_date=date.today() - timedelta(days=30)))
    assert urgent[0] > ordinary[0]
    assert urgent[1] == "Urgent"


def test_priority_is_transparent_for_uncertain_unverified_cases():
    score, label = case_priority(person(location_uncertain=True, source_confirmed=False, last_seen_lat=None, last_seen_lon=None))
    assert score >= 18
    assert label in {"Standard", "High", "Urgent"}
