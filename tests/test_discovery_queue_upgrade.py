from app.database import SessionLocal
from app.models import DiscoveryCandidate, MissingPerson


def create_event(client):
    return client.post(
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


def add_candidate(client, title="Person Missing Rajan Shrestha"):
    return client.post(
        "/admin/discovery/manual",
        data={
            "disaster_id": "1",
            "platform": "facebook",
            "url": "https://facebook.com/example/posts/123",
            "title": title,
            "snippet": "Rajan Shrestha age 41 last seen in Timure",
        },
        follow_redirects=False,
    )


def test_irrelevant_archive_and_restore(admin_client):
    create_event(admin_client)
    add_candidate(admin_client)

    response = admin_client.post(
        "/admin/discovery/1/status",
        data={"status_action": "irrelevant", "platform": "facebook", "view": "review"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        assert db.get(DiscoveryCandidate, 1).status == "irrelevant"

    page = admin_client.get("/admin/discovery?disaster_id=1&platform=facebook&view=irrelevant")
    assert "Rajan Shrestha" in page.text
    assert "Restore to Review" in page.text

    response = admin_client.post(
        "/admin/discovery/1/status",
        data={"status_action": "restore", "platform": "facebook", "view": "irrelevant"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        assert db.get(DiscoveryCandidate, 1).status == "needs_ai"


def test_findings_name_search(admin_client):
    create_event(admin_client)
    add_candidate(admin_client)
    page = admin_client.get(
        "/admin/discovery?disaster_id=1&platform=facebook&view=review&q=Rajan"
    )
    assert page.status_code == 200
    assert "Rajan Shrestha" in page.text
    page = admin_client.get(
        "/admin/discovery?disaster_id=1&platform=facebook&view=review&q=NoSuchPerson"
    )
    assert "Rajan Shrestha" not in page.text


def test_exact_published_name_is_isolated_in_duplicate_queue(admin_client):
    create_event(admin_client)
    add_candidate(admin_client)
    with SessionLocal() as db:
        db.add(MissingPerson(
            case_number="RF-0001",
            disaster_id=1,
            name="Rajan Shrestha",
            last_seen_location="Timure",
            published=True,
        ))
        db.commit()

    response = admin_client.post(
        "/admin/discovery/1/status",
        data={"status_action": "relevant", "platform": "facebook", "view": "review"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "view=duplicates" in response.headers["location"]
    with SessionLocal() as db:
        assert db.get(DiscoveryCandidate, 1).status == "possible_duplicate"
    page = admin_client.get(
        "/admin/discovery?disaster_id=1&platform=facebook&view=duplicates"
    )
    assert "Rajan Shrestha" in page.text
    assert "Possible Duplicate Sources" in page.text


def test_bulk_relevant_and_irrelevant_actions(admin_client):
    create_event(admin_client)
    add_candidate(admin_client, title="Person Missing One")
    add_candidate(admin_client, title="Person Missing Two")

    response = admin_client.post(
        "/admin/discovery/bulk-status",
        data={
            "disaster_id": "1",
            "platform": "facebook",
            "view": "review",
            "status_action": "irrelevant",
            "candidate_ids": ["1", "2"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        assert {item.status for item in db.query(DiscoveryCandidate).all()} == {"irrelevant"}

    response = admin_client.post(
        "/admin/discovery/bulk-status",
        data={
            "disaster_id": "1",
            "platform": "facebook",
            "view": "irrelevant",
            "status_action": "relevant",
            "candidate_ids": ["1", "2"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        assert {item.status for item in db.query(DiscoveryCandidate).all()} == {"relevant"}


def test_discovery_queue_template_has_bulk_controls():
    template = open("app/templates/admin_discovery.html", encoding="utf-8").read()
    assert "Select all" in template
    assert "Mark selected Relevant" in template
    assert "Mark selected Irrelevant" in template
    assert "candidate-checkbox" in template
    assert 'name="status_action" value="prefill"' in template
    assert "{% elif c.status == 'relevant' %}" in template


def test_one_click_prefill_opens_review_with_automatic_prefill(admin_client):
    create_event(admin_client)
    add_candidate(admin_client)

    response = admin_client.post(
        "/admin/discovery/1/status",
        data={"status_action": "prefill", "platform": "facebook", "view": "review"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/discovery/1?auto_prefill=1#chatgpt-prefill"
    with SessionLocal() as db:
        assert db.get(DiscoveryCandidate, 1).status == "relevant"
