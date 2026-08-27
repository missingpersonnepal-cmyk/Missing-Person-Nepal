from datetime import date

from app.database import SessionLocal
from app.models import Disaster, MissingPerson
from app.services.duplicates import find_duplicates


def test_similar_person_is_suggested():
    with SessionLocal() as db:
        disaster = Disaster(code="RF", name="Rasuwa Flood", disaster_type="flood", start_date=date(2026, 8, 26), affected_locations="Timure\nRasuwa")
        db.add(disaster)
        db.flush()
        person = MissingPerson(case_number="NP-2026-RF-00001", disaster_id=disaster.id, name="Anushka Pandey", age=32, last_seen_location="Timure, Rasuwa", public_contact_number="9812345678")
        db.add(person)
        db.commit()
        matches = find_duplicates(db, disaster_id=disaster.id, name="Anuska Pandey", location="Timure Rasuwa", age=32, phone="+9779812345678")
        assert matches
        assert matches[0][0].case_number == "NP-2026-RF-00001"
        assert matches[0][1] >= 80
