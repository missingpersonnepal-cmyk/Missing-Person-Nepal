from datetime import date

from app.database import SessionLocal
from app.models import Disaster, DiscoveryCandidate
from app.services.priority_sources import (
    PRIORITY_SOURCES,
    priority_manual_searches,
)
from app.services.wide_discovery import (
    collect_known_source_scopes,
    generate_wide_queries,
)


def event():
    return Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa\nTimure\nBetrawati",
    )


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


def test_priority_seed_sources_include_current_high_value_sharers():
    labels = {source.label for source in PRIORITY_SOURCES}
    assert "Saigrace Pokharel / Saigrace Official" in labels
    assert "Bikki Gurung" in labels
    assert "Hydropower Diaries" in labels
    assert "Medico Nepal" in labels


def test_priority_manual_searches_are_facebook_and_event_scoped():
    rows = priority_manual_searches(event())
    assert rows
    assert all("site:facebook.com" in row["query"] for row in rows)
    assert all(
        "Rasuwa" in row["query"] or "Timure" in row["query"]
        for row in rows
    )
    assert any("saigraceofficial" in row["query"].casefold() for row in rows)
    assert any("Hydropower Diaries" in row["query"] for row in rows)


def test_wide_plan_reserves_priority_source_lane():
    queries = generate_wide_queries(event(), source_scopes=[])
    folded = "\n".join(queries).casefold()
    assert "saigraceofficial" in folded
    assert "bikkigurungofficial" in folded
    assert "hydropower diaries" in folded
    assert all("after:2026-08-25" in query for query in queries)


def test_repeat_relevant_source_ranks_before_one_off_source():
    with SessionLocal() as db:
        disaster = Disaster(
            code="RF",
            name="Rasuwa Flood",
            disaster_type="flood",
            start_date=date(2026, 8, 26),
            affected_locations="Rasuwa\nTimure",
            active=True,
        )
        db.add(disaster)
        db.flush()

        rows = [
            ("https://facebook.com/repeater/posts/1", "relevant"),
            ("https://facebook.com/oneoff/posts/1", "relevant"),
            ("https://facebook.com/repeater/posts/2", "reviewed"),
        ]
        for url, status in rows:
            db.add(
                DiscoveryCandidate(
                    disaster_id=disaster.id,
                    platform="facebook",
                    query="test",
                    url=url,
                    title="Person missing",
                    snippet="Named person out of contact in Timure",
                    status=status,
                )
            )
        db.commit()

        scopes = collect_known_source_scopes(db, disaster.id)

    assert scopes[0] == "repeater"
    assert "oneoff" in scopes


def test_discovery_page_has_priority_sources_and_manual_add(admin_client):
    create_event(admin_client)
    page = admin_client.get(
        "/admin/discovery?disaster_id=1&platform=facebook"
    )
    assert page.status_code == 200
    assert "Priority missing-person sharers" in page.text
    assert "Saigrace Pokharel / Saigrace Official" in page.text
    assert "Hydropower Diaries" in page.text
    assert "Manual Add" in page.text
    assert 'id="manual-search-query"' in page.text
    assert "Full public post text / additional context" in page.text


def test_manual_intake_enriches_existing_candidate_context(admin_client):
    create_event(admin_client)

    first = admin_client.post(
        "/admin/discovery/manual",
        data={
            "disaster_id": "1",
            "platform": "facebook",
            "url": "https://facebook.com/example/posts/123",
            "title": "Person Missing",
            "snippet": "Indexed snippet only.",
            "search_query": 'site:facebook.com "Rasuwa" "missing person"',
        },
        follow_redirects=False,
    )
    assert first.status_code == 303

    second = admin_client.post(
        "/admin/discovery/manual",
        data={
            "disaster_id": "1",
            "platform": "facebook",
            "url": "https://facebook.com/example/posts/123",
            "snippet": "Contact 9800000000. Last seen at Timure.",
            "search_query": 'site:facebook.com "Saigrace" "Rasuwa"',
        },
        follow_redirects=False,
    )
    assert second.status_code == 303

    with SessionLocal() as db:
        rows = db.query(DiscoveryCandidate).all()
        assert len(rows) == 1
        assert "Indexed snippet only." in (rows[0].snippet or "")
        assert "[Manual context]" in (rows[0].snippet or "")
        assert "Contact 9800000000" in (rows[0].snippet or "")
