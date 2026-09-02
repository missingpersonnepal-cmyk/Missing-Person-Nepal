from datetime import date

from app.database import SessionLocal
from app.models import Disaster, Submission


def _active_disaster():
    with SessionLocal() as db:
        disaster = Disaster(code="PI", name="Public intake", disaster_type="flood", start_date=date(2026, 8, 26), active=True)
        db.add(disaster)
        db.commit()
        return disaster.id


def test_report_accepts_only_explicit_supported_gender_and_bounds_text(client):
    disaster_id = _active_disaster()
    response = client.post(
        "/report",
        data={
            "disaster_id": disaster_id,
            "name": "A" * 300,
            "name_ne": "B" * 300,
            "gender": "guessed from image",
            "last_seen_location": "Timure",
            "notes": "N" * 6000,
        },
    )

    assert response.status_code == 200
    with SessionLocal() as db:
        submission = db.query(Submission).one()
        assert len(submission.name) == 255
        assert len(submission.name_ne) == 255
        assert submission.gender is None
        assert len(submission.notes) == 5000


def test_report_rejects_invalid_age(client):
    disaster_id = _active_disaster()
    response = client.post(
        "/report",
        data={"disaster_id": disaster_id, "name": "Age test", "last_seen_location": "Rasuwa", "age": "121"},
    )

    assert response.status_code == 200
    assert "Age must be between 0 and 120" in response.text
    with SessionLocal() as db:
        assert db.query(Submission).count() == 0
