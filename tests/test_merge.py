from datetime import date

from app.database import SessionLocal
from app.models import Disaster, MissingPerson, Source


def test_admin_can_consolidate_duplicate_master_records(admin_client):
    with SessionLocal() as db:
        disaster = Disaster(code="RF", name="Rasuwa Flood", disaster_type="flood", start_date=date(2026, 8, 26), affected_locations="Rasuwa\nTimure")
        db.add(disaster); db.flush()
        target = MissingPerson(case_number="NP-2026-RF-00001", disaster_id=disaster.id, name="Anushka Pandey", last_seen_location="Timure", published=True)
        source = MissingPerson(case_number="NP-2026-RF-00002", disaster_id=disaster.id, name="Anuska Pandey", last_seen_location="Timure", name_ne="अनुष्का पाण्डे", published=True)
        db.add_all([target, source]); db.flush()
        db.add(Source(person_id=source.id, platform="facebook", url="https://facebook.com/post/abc"))
        db.commit()
        target_id, source_id = target.id, source.id

    response = admin_client.post(
        f"/admin/people/{source_id}/merge",
        data={"target_person_id": str(target_id)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        target = db.get(MissingPerson, target_id)
        source = db.get(MissingPerson, source_id)
        assert source.archived is True
        assert source.published is False
        assert target.name_ne == "अनुष्का पाण्डे"
        assert any(item.url == "https://facebook.com/post/abc" for item in target.sources)
