from datetime import date

from app.models import Disaster, DiscoveryCandidate
from app.services.candidate_extract import (
    candidate_mentions_multiple_people,
    extract_candidate_people_names,
    extract_candidate_prefill,
)
from app.services.source_images import extract_public_post_text_from_html


def disaster():
    return Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa\nTimure\nBetrawati",
    )


def candidate(title: str, snippet: str):
    return DiscoveryCandidate(
        disaster_id=1,
        platform="facebook",
        query="test",
        url="https://facebook.com/example/posts/123",
        title=title,
        snippet=snippet,
    )


def test_public_post_metadata_prefers_richer_text():
    html = """
    <html><head>
      <meta name="description" content="Short indexed text">
      <meta property="og:description"
        content="Missing person Nima Tamang, age 65, last seen at Timure. Contact 9704485859.">
    </head></html>
    """
    text = extract_public_post_text_from_html(html)
    assert text is not None
    assert "Nima Tamang" in text
    assert "9704485859" in text
    assert len(text) > len("Short indexed text")


def test_multiple_named_people_are_detected_from_one_post():
    row = candidate(
        "Person Missing Dorje Tamang and Pasang Tamang have been out of contact",
        "Their last known location was Timure, Rasuwa.",
    )
    assert extract_candidate_people_names(row) == [
        "Dorje Tamang",
        "Pasang Tamang",
    ]


def test_middle_dot_multi_person_text_does_not_turn_org_into_person():
    row = candidate(
        "New York teen, mother traveling in Nepal among missing",
        "Missing person Whitney Hatfield · Linda Lester ↪ Travel Nurse R Us. 2y",
    )
    names = extract_candidate_people_names(row)
    assert "Whitney Hatfield" in names
    assert "Linda Lester" in names
    assert all("Travel Nurse" not in item for item in names)


def test_full_public_post_text_improves_contact_prefill():
    row = candidate(
        "Missing person Nima Tamang",
        "Nima Tamang is missing from Timure.",
    )
    prefill = extract_candidate_prefill(
        row,
        disaster(),
        source_text=(
            "Missing person Nima Tamang, age 65, last seen at Timure. "
            "Please contact 9704485859 or 9862426561."
        ),
    )
    assert prefill["age"] == 65
    assert prefill["last_seen_location"] == "Timure"
    assert prefill["public_contact_number"] == "9704485859, 9862426561"
    assert "Public post text:" in prefill["identification_details"]


def test_plural_family_wording_flags_multiple_people():
    row = candidate(
        "Person Missing Kippa Lama, Dickey, and their sons",
        "They were last known to be in Timure, Rasuwa.",
    )
    assert candidate_mentions_multiple_people(row)


def _create_event(client):
    response = client.post(
        "/admin/events",
        data={
            "code": "RF",
            "name": "Rasuwa Flood",
            "disaster_type": "flood",
            "start_date": "2026-08-26",
            "affected_locations": "Rasuwa\nTimure",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _add_manual_candidate(client, url, title, snippet):
    response = client.post(
        "/admin/discovery/manual",
        data={
            "disaster_id": "1",
            "platform": "facebook",
            "url": url,
            "title": title,
            "snippet": snippet,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _disable_public_fetch(monkeypatch):
    async def no_text(_url):
        return None

    async def no_image(_url):
        return None

    monkeypatch.setattr(
        "app.routes.admin.discover_public_post_text",
        no_text,
    )
    monkeypatch.setattr(
        "app.routes.admin.discover_public_post_image",
        no_image,
    )


def test_multi_person_source_can_create_two_entries_and_stays_relevant(
    admin_client,
    monkeypatch,
):
    from app.database import SessionLocal
    from app.models import DiscoveryCandidate, Submission

    _disable_public_fetch(monkeypatch)
    _create_event(admin_client)
    _add_manual_candidate(
        admin_client,
        "https://facebook.com/example/posts/multi123",
        "Person Missing Dorje Tamang and Pasang Tamang have been out of contact",
        "Their last known location was Timure, Rasuwa.",
    )

    page = admin_client.get("/admin/discovery/1")
    assert page.status_code == 200
    assert "Possible multiple missing people" in page.text
    assert "Dorje Tamang" in page.text
    assert "Pasang Tamang" in page.text

    first = admin_client.post(
        "/admin/discovery/1/submission",
        data={
            "name": "Dorje Tamang",
            "last_seen_location": "Timure",
        },
        follow_redirects=False,
    )
    assert first.status_code == 303
    assert "#person-entry-form" in first.headers["location"]

    second = admin_client.post(
        "/admin/discovery/1/submission",
        data={
            "name": "Pasang Tamang",
            "last_seen_location": "Timure",
        },
        follow_redirects=False,
    )
    assert second.status_code == 303

    with SessionLocal() as db:
        candidate_row = db.get(DiscoveryCandidate, 1)
        assert candidate_row.status == "relevant"
        names = {
            item.name
            for item in db.query(Submission).all()
        }
        assert names == {"Dorje Tamang", "Pasang Tamang"}


def test_duplicate_warning_only_links_exact_published_case(
    admin_client,
    monkeypatch,
):
    from app.database import SessionLocal
    from app.models import MissingPerson

    _disable_public_fetch(monkeypatch)
    _create_event(admin_client)
    with SessionLocal() as db:
        db.add(MissingPerson(
            case_number="RF-0001",
            disaster_id=1,
            name="Yuvraj Bhandari",
            last_seen_location="Timure",
            published=True,
        ))
        db.add(MissingPerson(
            case_number="RF-0002",
            disaster_id=1,
            name="Dinesh Bhandari Similar",
            last_seen_location="Timure",
            published=True,
        ))
        db.commit()
    _add_manual_candidate(
        admin_client,
        "https://facebook.com/example/posts/current",
        "Missing Yuvraj Bhandari",
        "Yuvraj Bhandari was last seen in Timure wearing a blue jacket.",
    )

    page = admin_client.get("/admin/discovery/1")
    exact = admin_client.get(
        "/admin/discovery/1/duplicate-check",
        params={"name": "Yuvraj Bhandari"},
    ).json()
    similar = admin_client.get(
        "/admin/discovery/1/duplicate-check",
        params={"name": "Dinesh Bhandari"},
    ).json()

    assert page.status_code == 200
    assert "View published case" in page.text
    assert exact["people"] == [{
        "id": exact["people"][0]["id"],
        "case_number": "RF-0001",
        "name": "Yuvraj Bhandari",
        "age": None,
        "last_seen_location": "Timure",
        "score": 100.0,
        "exact_name": True,
        "public_url": "/person/RF-0001",
        "source_already_attached": False,
    }]
    assert similar["people"] == []
    assert "Other posts mentioning" not in page.text


def test_exact_duplicate_requires_attach_or_explicit_continue(
    admin_client,
    monkeypatch,
):
    from app.database import SessionLocal
    from app.models import Disaster, MissingPerson, Source, Submission

    _disable_public_fetch(monkeypatch)
    _create_event(admin_client)

    with SessionLocal() as db:
        person = MissingPerson(
            case_number="RF-0001",
            disaster_id=1,
            name="Nima Tamang",
            last_seen_location="Timure",
            published=False,
        )
        db.add(person)
        db.commit()
        person_id = person.id

    _add_manual_candidate(
        admin_client,
        "https://facebook.com/example/posts/nima456",
        "Person Missing Nima Tamang",
        "Nima Tamang is missing from Timure.",
    )

    blocked = admin_client.post(
        "/admin/discovery/1/submission",
        data={
            "name": "Nima Tamang",
            "last_seen_location": "Timure",
        },
        follow_redirects=False,
    )
    assert blocked.status_code == 409

    attached = admin_client.post(
        "/admin/discovery/1/submission",
        data={
            "name": "Nima Tamang",
            "last_seen_location": "Timure",
            "duplicate_action": f"attach:{person_id}",
        },
        follow_redirects=False,
    )
    assert attached.status_code == 303

    with SessionLocal() as db:
        assert (
            db.query(Source)
            .filter(
                Source.person_id == person_id,
                Source.url == "https://facebook.com/example/posts/nima456",
            )
            .count()
            == 1
        )
        assert db.query(Submission).count() == 0


def test_pending_duplicate_requires_explicit_continue(
    admin_client,
    monkeypatch,
):
    from app.database import SessionLocal
    from app.models import Submission

    _disable_public_fetch(monkeypatch)
    _create_event(admin_client)

    with SessionLocal() as db:
        db.add(
            Submission(
                disaster_id=1,
                kind="missing_report",
                status="pending",
                name="Rajan Shrestha",
                last_seen_location="Timure",
            )
        )
        db.commit()

    _add_manual_candidate(
        admin_client,
        "https://facebook.com/example/posts/rajan789",
        "Person Missing Rajan Shrestha",
        "Rajan Shrestha is missing from Timure.",
    )

    blocked = admin_client.post(
        "/admin/discovery/1/submission",
        data={
            "name": "Rajan Shrestha",
            "last_seen_location": "Timure",
        },
        follow_redirects=False,
    )
    assert blocked.status_code == 409

    continued = admin_client.post(
        "/admin/discovery/1/submission",
        data={
            "name": "Rajan Shrestha",
            "last_seen_location": "Timure",
            "duplicate_action": "continue",
        },
        follow_redirects=False,
    )
    assert continued.status_code == 303

    with SessionLocal() as db:
        assert (
            db.query(Submission)
            .filter(Submission.name == "Rajan Shrestha")
            .count()
            == 2
        )


def test_discovery_page_contains_scroll_restore_hooks(
    admin_client,
):
    _create_event(admin_client)
    _add_manual_candidate(
        admin_client,
        "https://facebook.com/example/posts/scroll123",
        "Person Missing Nima Tamang",
        "Nima Tamang is missing from Timure.",
    )
    page = admin_client.get(
        "/admin/discovery?disaster_id=1&platform=facebook&view=review"
    )
    assert page.status_code == 200
    assert "mp-discovery-scroll:" in page.text
    assert "discovery-status-form" in page.text
    assert "discovery-review-link" in page.text
