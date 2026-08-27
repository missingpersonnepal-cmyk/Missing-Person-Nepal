from datetime import date

from app.database import SessionLocal
from app.models import Disaster, MissingPerson, Source


def test_public_api_excludes_private_fields(client):
    with SessionLocal() as db:
        disaster = Disaster(code="RF", name="Rasuwa Flood", disaster_type="flood", start_date=date(2026, 8, 26), affected_locations="Rasuwa")
        db.add(disaster); db.flush()
        person = MissingPerson(
            case_number="NP-2026-RF-00001",
            disaster_id=disaster.id,
            name="Person A",
            last_seen_location="Rasuwa",
            residential_address_private="Private House Address",
            private_contact_number="9800000000",
            public_contact_number="9811111111",
            published=True,
        )
        db.add(person); db.flush()
        db.add(Source(person_id=person.id, platform="facebook", url="https://facebook.com/post/1"))
        db.commit()

    response = client.get("/api/v1/people/NP-2026-RF-00001")
    assert response.status_code == 200
    payload = response.json()
    assert payload["public_contact_number"] == "9811111111"
    assert "residential_address_private" not in payload
    assert "private_contact_number" not in payload
    assert payload["sources"][0]["url"] == "https://facebook.com/post/1"
