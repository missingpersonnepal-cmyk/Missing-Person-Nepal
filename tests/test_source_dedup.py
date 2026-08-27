from datetime import date

from app.database import SessionLocal
from app.models import Disaster, MissingPerson, Source


def test_source_url_unique_per_person():
    from sqlalchemy.exc import IntegrityError

    with SessionLocal() as db:
        d = Disaster(code="RF", name="Rasuwa Flood", disaster_type="flood", start_date=date(2026, 8, 26), affected_locations="Rasuwa")
        db.add(d); db.flush()
        p = MissingPerson(case_number="NP-2026-RF-00001", disaster_id=d.id, name="Person A", last_seen_location="Rasuwa")
        db.add(p); db.flush()
        db.add(Source(person_id=p.id, platform="facebook", url="https://facebook.com/post/1")); db.commit()
        db.add(Source(person_id=p.id, platform="facebook", url="https://facebook.com/post/1"))
        try:
            db.commit()
            assert False, "Expected duplicate source URL to be rejected"
        except IntegrityError:
            db.rollback()


def test_same_source_url_can_reference_different_people():
    with SessionLocal() as db:
        d = Disaster(code="RF2", name="Rasuwa Flood 2", disaster_type="flood", start_date=date(2026, 8, 27), affected_locations="Rasuwa")
        db.add(d); db.flush()
        p1 = MissingPerson(case_number="NP-2026-RF2-00001", disaster_id=d.id, name="Person A", last_seen_location="Rasuwa")
        p2 = MissingPerson(case_number="NP-2026-RF2-00002", disaster_id=d.id, name="Person B", last_seen_location="Rasuwa")
        db.add_all([p1, p2]); db.flush()
        url = "https://facebook.com/post/list-1"
        db.add_all([Source(person_id=p1.id, platform="facebook", url=url), Source(person_id=p2.id, platform="facebook", url=url)])
        db.commit()
        assert db.query(Source).filter(Source.url == url).count() == 2
