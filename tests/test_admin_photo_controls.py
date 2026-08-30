from datetime import date

from app.config import settings
from app.database import SessionLocal
from app.models import Disaster, MissingPerson


def test_admin_can_remove_case_photo_and_public_uses_placeholder(admin_client):
    filename = "remove-me.jpg"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / filename).write_bytes(b"test-image")
    with SessionLocal() as db:
        disaster = Disaster(
            code="RF",
            name="Rasuwa Flood",
            disaster_type="flood",
            start_date=date(2026, 8, 26),
            affected_locations="Rasuwa",
        )
        db.add(disaster)
        db.flush()
        person = MissingPerson(
            case_number="NP-2026-RF-00001",
            disaster_id=disaster.id,
            name="Photo Test Person",
            last_seen_location="Rasuwa",
            photo_path=filename,
            published=True,
        )
        db.add(person)
        db.commit()
        person_id = person.id

    response = admin_client.post(
        f"/admin/people/{person_id}/photo/remove",
        follow_redirects=False,
    )

    assert response.status_code == 303
    with SessionLocal() as db:
        assert db.get(MissingPerson, person_id).photo_path is None
    assert not (settings.upload_dir / filename).exists()
    public = admin_client.get("/person/NP-2026-RF-00001")
    assert "/static/default-person.svg" in public.text
