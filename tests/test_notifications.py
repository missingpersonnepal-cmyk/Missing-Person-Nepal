from datetime import date
from uuid import uuid4

from app.database import SessionLocal
from app.models import Disaster, MissingPerson, NotificationOutbox, NotificationSubscription, PersonCaseState
from app.services.notifications import add_subscription, drain_pending_notifications, enqueue_case_notifications, mask_destination
from app.services.notifications.messages import CASE_UPDATED, IDENTIFIED_DECEASED


def create_person():
    suffix = uuid4().hex[:6].upper()
    with SessionLocal() as db:
        disaster = Disaster(
            code=f"RF{suffix}",
            name="Rasuwa Flood",
            disaster_type="flood",
            start_date=date(2026, 8, 26),
            affected_locations="Rasuwa",
        )
        db.add(disaster)
        db.flush()
        person = MissingPerson(
            case_number=f"NP-2026-{suffix}-00001",
            disaster_id=disaster.id,
            name="Notification Test",
            last_seen_location="Rasuwa",
            published=True,
        )
        db.add(person)
        db.flush()
        db.add(PersonCaseState(person_id=person.id, status="missing"))
        db.commit()
        return person.id, person.case_number


def test_sms_and_email_opt_in_are_private_and_masked(admin_client):
    person_id, case_number = create_person()

    response = admin_client.post(
        f"/admin/people/{person_id}/notifications",
        data={"channel": "sms", "destination": "9841234591"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    admin_client.post(
        f"/admin/people/{person_id}/notifications",
        data={"channel": "email", "destination": "user@example.com"},
        follow_redirects=False,
    )

    with SessionLocal() as db:
        assert db.query(NotificationSubscription).count() == 2
    page = admin_client.get(f"/admin/people/{person_id}")
    assert "98******91" in page.text
    assert "u***@example.com" in page.text
    assert "9841234591" not in page.text
    assert "user@example.com" not in page.text
    public = admin_client.get(f"/person/{case_number}")
    assert "9841234591" not in public.text
    assert "user@example.com" not in public.text


def test_status_change_enqueues_once_and_disabled_provider_skips(admin_client):
    person_id, _case_number = create_person()
    with SessionLocal() as db:
        add_subscription(db, person_id, "sms", "9841234591")
        db.commit()

    first = admin_client.post(
        f"/admin/people/{person_id}/status",
        data={"case_status": "found", "status_note": "Located safely"},
        follow_redirects=False,
    )
    second = admin_client.post(
        f"/admin/people/{person_id}/status",
        data={"case_status": "found", "status_note": "Located safely"},
        follow_redirects=False,
    )

    assert first.status_code == 303
    assert second.status_code == 303
    with SessionLocal() as db:
        rows = db.query(NotificationOutbox).all()
        assert len(rows) == 1
        assert rows[0].event_type == "FOUND_ALIVE"
        assert "has been found" in rows[0].body
        assert drain_pending_notifications(db)["skipped"] == 1
        assert rows[0].status == "pending"


def test_identified_and_case_update_wording_is_neutral(admin_client):
    person_id, _case_number = create_person()
    with SessionLocal() as db:
        add_subscription(db, person_id, "email", "user@example.com")
        db.commit()

    admin_client.post(
        f"/admin/people/{person_id}/status",
        data={"case_status": "identified", "status_note": "Authority confirmed"},
        follow_redirects=False,
    )
    with SessionLocal() as db:
        row = db.query(NotificationOutbox).filter_by(event_type=IDENTIFIED_DECEASED).one()
        assert "movement in the file" in row.body
        assert "cause of death" not in row.body.casefold()

    person_id, _case_number = create_person()
    with SessionLocal() as db:
        add_subscription(db, person_id, "sms", "9841234591")
        db.commit()
    admin_client.post(
        f"/admin/people/{person_id}/edit",
        data={
            "name": "Notification Test",
            "last_seen_location": "Rasuwa",
            "meaningful_update": "1",
        },
        follow_redirects=False,
    )
    with SessionLocal() as db:
        row = db.query(NotificationOutbox).filter_by(event_type=CASE_UPDATED).one()
        assert "update to the missing-person file" in row.body


def test_mask_destination_fallbacks():
    assert mask_destination("9841234591", "sms") == "98******91"
    assert mask_destination("user@example.com", "email") == "u***@example.com"


def test_case_updates_use_event_instance_dedupe_keys(admin_client):
    person_id, _case_number = create_person()
    with SessionLocal() as db:
        add_subscription(db, person_id, "sms", "9841234591")
        person = db.get(MissingPerson, person_id)
        assert enqueue_case_notifications(db, person, CASE_UPDATED, event_instance="update-1") == 1
        assert enqueue_case_notifications(db, person, CASE_UPDATED, event_instance="update-1") == 0
        assert enqueue_case_notifications(db, person, CASE_UPDATED, event_instance="update-2") == 1
        db.commit()

    with SessionLocal() as db:
        rows = db.query(NotificationOutbox).filter_by(event_type=CASE_UPDATED).all()
        assert len(rows) == 2
        assert len({row.dedupe_key for row in rows}) == 2


def test_idempotency_key_deduplicates_same_event_but_allows_later_updates():
    person_id, _case_number = create_person()
    with SessionLocal() as db:
        add_subscription(db, person_id, "sms", "9841234591")
        db.commit()

    with SessionLocal() as db:
        person = db.get(MissingPerson, person_id)
        assert person is not None

        first = enqueue_case_notifications(
            db,
            person,
            CASE_UPDATED,
            update_note="First meaningful update",
            idempotency_key="case-update-001",
        )
        duplicate = enqueue_case_notifications(
            db,
            person,
            CASE_UPDATED,
            update_note="First meaningful update",
            idempotency_key="case-update-001",
        )
        later = enqueue_case_notifications(
            db,
            person,
            CASE_UPDATED,
            update_note="Later meaningful update",
            idempotency_key="case-update-002",
        )
        db.commit()

        rows = (
            db.query(NotificationOutbox)
            .filter_by(person_id=person_id, event_type=CASE_UPDATED)
            .order_by(NotificationOutbox.id)
            .all()
        )
        assert first == 1
        assert duplicate == 0
        assert later == 1
        assert len(rows) == 2
        assert rows[0].idempotency_key == "CASE_UPDATED:case-update-001"
        assert rows[1].idempotency_key == "CASE_UPDATED:case-update-002"


def test_same_raw_key_is_namespaced_by_event_type():
    person_id, _case_number = create_person()
    with SessionLocal() as db:
        add_subscription(db, person_id, "email", "user@example.com")
        db.commit()

    with SessionLocal() as db:
        person = db.get(MissingPerson, person_id)
        assert person is not None

        assert enqueue_case_notifications(
            db,
            person,
            CASE_UPDATED,
            idempotency_key="event-001",
        ) == 1
        assert enqueue_case_notifications(
            db,
            person,
            IDENTIFIED_DECEASED,
            idempotency_key="event-001",
        ) == 1
        db.commit()

        rows = db.query(NotificationOutbox).filter_by(
            person_id=person_id,
        ).all()
        assert len(rows) == 2
        assert {row.idempotency_key for row in rows} == {
            "CASE_UPDATED:event-001",
            "IDENTIFIED_DECEASED:event-001",
        }

