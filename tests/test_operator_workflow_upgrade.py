import json
from datetime import date
from pathlib import Path

from app.database import SessionLocal
from app.models import (
    Disaster,
    DiscoveryCandidate,
    DiscoverySearchTag,
    DiscoverySourceSeed,
    MissingPerson,
    PersonCaseState,
    Submission,
)
from app.services.candidate_chatgpt_prefill import parse_candidate_chatgpt_prefill
from app.services.priority_sources import discovered_source_activity
from app.services.wide_discovery import generate_wide_queries


def create_event(client):
    response = client.post(
        "/admin/events",
        data={
            "code": "RF",
            "name": "Rasuwa Flood",
            "disaster_type": "flood",
            "start_date": "2026-08-26",
            "affected_locations": "Rasuwa\nTimure\nBetrawati",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_chatgpt_parser_accepts_fence_and_trailing_comma():
    raw = "```json\n{\"people\":[{\"name\":\"A Person\",\"age\":32,\"last_seen_location\":\"Timure\",}],\"source_notes\":null,}\n```"
    payload = parse_candidate_chatgpt_prefill(raw)
    assert payload["people"][0]["name"] == "A Person"
    assert payload["people"][0]["age"] == 32


def test_chatgpt_parser_repairs_missing_comma_between_properties():
    payload = parse_candidate_chatgpt_prefill(
        '{"people":[{"name":"A Person" "age":32, "last_seen_location":"Timure"}]}'
    )
    assert payload["people"][0]["name"] == "A Person"
    assert payload["people"][0]["age"] == 32


def test_chatgpt_parser_accepts_python_style_dict():
    payload = parse_candidate_chatgpt_prefill(
        "{'people': [{'name': 'B Person', 'last_seen_location': 'Rasuwa'}], 'source_notes': None}"
    )
    assert payload["people"][0]["name"] == "B Person"


def test_custom_tag_is_persisted_and_enters_wide_plan(admin_client):
    create_event(admin_client)
    response = admin_client.post(
        "/admin/discovery/search-tags",
        data={"disaster_id": "1", "platform": "facebook", "tag": "hydropower worker"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        row = db.query(DiscoverySearchTag).one()
        disaster = db.get(Disaster, 1)
        queries = generate_wide_queries(disaster, custom_tags=[row.tag], max_queries=12)
    assert any("hydropower worker" in query for query in queries)


def test_manual_source_is_persisted(admin_client):
    create_event(admin_client)
    response = admin_client.post(
        "/admin/discovery/source-seeds",
        data={
            "disaster_id": "1",
            "platform": "facebook",
            "label": "Helpful Group",
            "source": "https://www.facebook.com/groups/helpfulgroup/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        row = db.query(DiscoverySourceSeed).one()
        assert row.scope == "groups/helpfulgroup"


def test_repeated_candidate_source_is_auto_discovered():
    with SessionLocal() as db:
        disaster = Disaster(
            code="RF", name="Rasuwa Flood", disaster_type="flood",
            start_date=date(2026, 8, 26), affected_locations="Rasuwa\nTimure",
        )
        db.add(disaster)
        db.flush()
        for index, status in enumerate(["needs_ai", "relevant", "reviewed"], 1):
            db.add(DiscoveryCandidate(
                disaster_id=disaster.id,
                platform="facebook",
                query="q",
                url=f"https://facebook.com/repeater/posts/{index}",
                title="Person missing",
                snippet="Named person out of contact in Timure",
                status=status,
            ))
        db.commit()
        rows = discovered_source_activity(db, disaster.id)
    assert rows[0]["scope"] == "repeater"
    assert rows[0]["posts"] == 3
    assert rows[0]["confirmed"] == 2


def test_batch_chatgpt_prefill_creates_multiple_pending_entries(admin_client):
    create_event(admin_client)
    with SessionLocal() as db:
        db.add(DiscoveryCandidate(
            disaster_id=1,
            platform="facebook",
            query="q",
            url="https://facebook.com/example/posts/123",
            title="Two people missing",
            snippet="A Person and B Person are missing in Timure",
            status="relevant",
        ))
        db.commit()
    raw = json.dumps({"people": [
        {"name": "A Person", "last_seen_location": "Timure"},
        {"name": "B Person", "last_seen_location": "Timure"},
    ]})
    response = admin_client.post(
        "/admin/discovery/1/chatgpt-prefill/batch",
        data={"result_json": raw},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        rows = db.query(Submission).filter(Submission.status == "pending").all()
        assert {row.name for row in rows} == {"A Person", "B Person"}


def test_batch_skips_exact_existing_name_instead_of_auto_attaching(admin_client):
    create_event(admin_client)
    with SessionLocal() as db:
        person = MissingPerson(
            case_number="RF-000001", disaster_id=1, name="A Person",
            last_seen_location="Timure", published=False,
        )
        db.add(person)
        db.add(DiscoveryCandidate(
            disaster_id=1, platform="facebook", query="q",
            url="https://facebook.com/example/posts/123",
            title="Two missing", snippet="A Person and B Person", status="relevant",
        ))
        db.commit()
    raw = json.dumps({"people": [
        {"name": "A Person", "last_seen_location": "Timure"},
        {"name": "B Person", "last_seen_location": "Timure"},
    ]})
    response = admin_client.post(
        "/admin/discovery/1/chatgpt-prefill/batch",
        data={"result_json": raw},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "batch_duplicates=1" in response.headers["location"]
    with SessionLocal() as db:
        assert db.query(Submission).filter(Submission.name == "A Person").count() == 0
        assert db.query(Submission).filter(Submission.name == "B Person").count() == 1


def test_person_status_filters_and_unpublishes_resolved_case(admin_client):
    create_event(admin_client)
    with SessionLocal() as db:
        person = MissingPerson(
            case_number="RF-000001", disaster_id=1, name="A Person",
            last_seen_location="Timure", published=True,
        )
        db.add(person)
        db.commit()
        person_id = person.id

    response = admin_client.post(
        f"/admin/people/{person_id}/status",
        data={"case_status": "found", "status_note": "Located safely"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        person = db.get(MissingPerson, person_id)
        state = db.get(PersonCaseState, person_id)
        assert state.status == "found"
        assert person.published is False

    page = admin_client.get("/admin/people?case_status=found")
    assert page.status_code == 200
    assert "A Person" in page.text
    assert "FOUND ALIVE" in page.text


def test_admin_people_template_has_edit_found_identified_actions():
    template = Path("app/templates/admin_people.html").read_text(encoding="utf-8")
    assert ">Edit<" in template
    assert 'value="found"' in template
    assert 'value="identified"' in template
    assert "Found Alive" in template
    assert "Identified / Deceased" in template


def test_discovery_template_has_true_add_tag_and_add_source_forms():
    template = Path("app/templates/admin_discovery.html").read_text(encoding="utf-8")
    assert "Custom Search Tags / Phrases" in template
    assert 'action="/admin/discovery/search-tags"' in template
    assert "Search Tags" in template
    assert "Track Source Accounts" in template
    assert "Suggested sources to track" in template
    assert 'action="/admin/discovery/source-seeds"' in template
    assert "Track this source" in template


def test_review_template_has_batch_prefill():
    template = Path("app/templates/admin_discovery_review.html").read_text(encoding="utf-8")
    assert "Create All Non-Duplicate People as Pending Entries" in template
    assert "/chatgpt-prefill/parse" in template
    assert "Batch mode" in template


def test_existing_productive_source_scope_keeps_small_budget_slot():
    disaster = Disaster(
        code="RF2", name="Rasuwa Flood", disaster_type="flood",
        start_date=date(2026, 8, 26), affected_locations="Rasuwa\nTimure",
    )
    queries = generate_wide_queries(
        disaster,
        source_scopes=["bikki.gurung"],
        max_queries=12,
    )
    assert len(queries) == 12
    assert any("site:facebook.com/bikki.gurung" in query for query in queries)


def test_user_source_scope_and_custom_tag_both_get_bounded_slots():
    disaster = Disaster(
        code="RF3", name="Rasuwa Flood", disaster_type="flood",
        start_date=date(2026, 8, 26), affected_locations="Rasuwa\nTimure",
    )
    queries = generate_wide_queries(
        disaster,
        source_scopes=["learnedsource"],
        manual_source_scopes=["groups/manualgroup"],
        manual_sources=[("Manual Group", "groups/manualgroup")],
        custom_tags=["hydropower worker"],
        max_queries=18,
    )
    folded = "\n".join(queries).casefold()
    assert "hydropower worker" in folded
    assert "site:facebook.com/groups/manualgroup" in folded
    assert "site:facebook.com/learnedsource" in folded
