from app.models import MissingPerson, Submission
from app.services.master_records import apply_submission_to_master


def test_attach_fills_blank_master_fields():
    person = MissingPerson(
        case_number="RF-0001",
        disaster_id=1,
        name="Example Person",
        age=None,
        last_seen_location="Unknown",
        public_contact_number=None,
    )

    submission = Submission(
        disaster_id=1,
        name="Example Person",
        age=32,
        last_seen_location="Timure",
        public_contact_number="9800000000",
        identification_details="Works at project site",
    )

    updated = apply_submission_to_master(
        person,
        submission,
    )

    assert person.age == 32
    assert person.last_seen_location == "Timure"
    assert person.public_contact_number == "9800000000"
    assert person.identification_details == "Works at project site"

    assert "age" in updated
    assert "last_seen_location" in updated


def test_attach_never_overwrites_existing_master_information():
    person = MissingPerson(
        case_number="RF-0002",
        disaster_id=1,
        name="Example Person",
        age=40,
        last_seen_location="Verified Location",
        public_contact_number="1111111111",
    )

    submission = Submission(
        disaster_id=1,
        name="Example Person",
        age=32,
        last_seen_location="Unverified Location",
        public_contact_number="2222222222",
    )

    apply_submission_to_master(
        person,
        submission,
    )

    assert person.age == 40
    assert person.last_seen_location == "Verified Location"
    assert person.public_contact_number == "1111111111"
