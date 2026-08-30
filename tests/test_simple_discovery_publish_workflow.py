from datetime import date
import json
from pathlib import Path

from app.database import SessionLocal
from app.models import Disaster, DiscoveryCandidate, MissingPerson, PersonCaseState, Source, Submission


def create_event(admin_client):
    response = admin_client.post(
        "/admin/events",
        data={
            "code": "RF",
            "name": "Rasuwa Flood",
            "disaster_type": "flood",
            "start_date": "2026-08-26",
            "affected_locations": "Rasuwa\nTimure",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def add_relevant_candidate():
    with SessionLocal() as db:
        db.add(
            DiscoveryCandidate(
                disaster_id=1,
                platform="facebook",
                query="test",
                url="https://www.facebook.com/example/posts/123",
                title="PERSON MISSING Rajesh Shrestha",
                snippet="Rajesh Shrestha has been out of contact since yesterday morning from Timure.",
                status="relevant",
            )
        )
        db.commit()


def person(name: str):
    return {
        "name": name,
        "name_ne": None,
        "age": None,
        "gender": None,
        "last_seen_date": None,
        "last_seen_time": None,
        "last_seen_location": "Timure, Rasuwa",
        "clothing": None,
        "identification_details": "Reported out of contact from Timure.",
        "public_contact_number": None,
    }


def test_batch_save_and_publish_puts_people_on_public_hub(admin_client):
    create_event(admin_client)
    add_relevant_candidate()

    payload = {"people": [person("Rajesh Shrestha")], "source_notes": "Reviewed public evidence"}
    response = admin_client.post(
        "/admin/discovery/1/chatgpt-prefill/batch",
        data={"result_json": json.dumps(payload), "save_mode": "publish"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "batch_published=1" in response.headers["location"]

    with SessionLocal() as db:
        master = db.query(MissingPerson).filter_by(name="Rajesh Shrestha").one()
        assert master.published is True
        assert master.archived is False
        assert db.get(PersonCaseState, master.id).status == "missing"
        source = db.query(Source).filter_by(person_id=master.id).one()
        assert source.url == "https://www.facebook.com/example/posts/123"

    public = admin_client.get("/?q=Rajesh")
    assert "Rajesh Shrestha" in public.text

    duplicate_check = admin_client.get(
        "/admin/discovery/1/duplicate-check",
        params={"name": "Rajesh Shrestha"},
    )
    assert duplicate_check.status_code == 200
    assert duplicate_check.json()["people"] == []


def test_removed_person_is_not_submitted_when_payload_contains_only_kept_people(admin_client):
    create_event(admin_client)
    add_relevant_candidate()

    # The browser's Remove button rewrites result_json to contain only the kept list.
    payload = {"people": [person("Rajesh Shrestha")], "source_notes": None}
    response = admin_client.post(
        "/admin/discovery/1/chatgpt-prefill/batch",
        data={"result_json": json.dumps(payload), "save_mode": "publish"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        names = [row.name for row in db.query(MissingPerson).all()]
    assert names == ["Rajesh Shrestha"]


def test_batch_multi_person_save_uses_default_images_unless_explicitly_enabled(
    admin_client, monkeypatch
):
    create_event(admin_client)
    add_relevant_candidate()

    async def source_image(_url):
        return "https://scontent.xx.fbcdn.net/shared.jpg"

    async def download_image(_url, _destination):
        return "shared.jpg"

    monkeypatch.setattr("app.routes.admin.discover_public_post_image", source_image)
    monkeypatch.setattr("app.routes.admin.download_public_source_image", download_image)
    payload = {
        "people": [person("Rajesh Shrestha"), person("Kiran Shrestha")],
        "source_notes": None,
    }

    response = admin_client.post(
        "/admin/discovery/1/chatgpt-prefill/batch",
        data={"result_json": json.dumps(payload), "save_mode": "publish"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with SessionLocal() as db:
        assert {item.photo_path for item in db.query(MissingPerson).all()} == {None}


def test_batch_save_keeps_source_image_when_operator_explicitly_enables_it(
    admin_client, monkeypatch
):
    create_event(admin_client)
    add_relevant_candidate()

    async def source_image(_url):
        return "https://scontent.xx.fbcdn.net/shared.jpg"

    async def download_image(_url, _destination):
        return "shared.jpg"

    monkeypatch.setattr("app.routes.admin.discover_public_post_image", source_image)
    monkeypatch.setattr("app.routes.admin.download_public_source_image", download_image)

    response = admin_client.post(
        "/admin/discovery/1/chatgpt-prefill/batch",
        data={
            "result_json": json.dumps({"people": [person("Rajesh Shrestha")]}),
            "save_mode": "publish",
            "include_source_image": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with SessionLocal() as db:
        assert db.query(MissingPerson).one().photo_path == "shared.jpg"


def test_pending_submission_can_be_approved_and_published_in_one_click(admin_client):
    create_event(admin_client)
    with SessionLocal() as db:
        db.add(
            Submission(
                disaster_id=1,
                kind="missing_report",
                status="pending",
                name="Existing Pending Person",
                last_seen_location="Rasuwa",
            )
        )
        db.commit()

    response = admin_client.post(
        "/admin/submissions/1/approve-new",
        data={"publish": "1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        master = db.query(MissingPerson).filter_by(name="Existing Pending Person").one()
        assert master.published is True


def test_discovery_templates_expose_simple_add_remove_publish_controls():
    discovery = Path("app/templates/admin_discovery.html").read_text(encoding="utf-8")
    review = Path("app/templates/admin_discovery_review.html").read_text(encoding="utf-8")
    people = Path("app/templates/admin_people.html").read_text(encoding="utf-8")
    submissions = Path("app/templates/admin_submissions.html").read_text(encoding="utf-8")
    index = Path("app/templates/index.html").read_text(encoding="utf-8")
    person = Path("app/templates/person.html").read_text(encoding="utf-8")

    assert "Add Search Tag" in discovery
    assert "Track Source Accounts" in discovery
    assert "Done Posts" in discovery
    assert "Public visibility is controlled separately" in discovery
    assert "data-ai-remove" in review
    assert "id=\"chatgpt-add-blank\"" in review
    assert "Save & Publish Selected People" in review
    assert "Save & Publish" in review
    assert "Publish" in people
    assert "Approve & Publish" in submissions
    assert "admin_username" in index
    assert "default-person.svg" in index
    assert "admin_username" in person
    assert "default-person.svg" in person
