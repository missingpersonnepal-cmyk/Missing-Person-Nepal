import json
from datetime import date
from pathlib import Path

from app.database import SessionLocal
from app.models import Disaster, DiscoveryCandidate
from app.services.openai_prefill import (
    _build_request_payload,
    _extract_output_text,
    openai_prefill_status,
)


def _event_and_candidate():
    disaster = Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa\nTimure",
    )
    candidate = DiscoveryCandidate(
        id=10,
        disaster_id=1,
        platform="facebook",
        query="q",
        url="https://facebook.com/example/posts/123",
        title="Two people missing",
        snippet="A Person and B Person are missing in Timure.",
        status="relevant",
    )
    return disaster, candidate


def test_openai_request_uses_strict_structured_output_and_public_evidence_only():
    disaster, candidate = _event_and_candidate()
    payload = _build_request_payload(
        disaster,
        candidate,
        source_post_text="A Person age 30. B Person age 44.",
        ocr_text="Contact 9812345678",
        source_image_url="https://scontent.xx.fbcdn.net/example.jpg",
        model="gpt-5-mini",
    )
    assert payload["model"] == "gpt-5-mini"
    assert payload["store"] is False
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["schema"]["properties"]["people"]["type"] == "array"
    content = payload["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert "9812345678" in content[0]["text"]
    assert any(item.get("type") == "input_image" for item in content)
    assert "Never identify a person from a face" in payload["instructions"]


def test_output_text_is_read_from_responses_api_message():
    raw = json.dumps({"people": [{"name": "A Person"}], "source_notes": None})
    payload = {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": raw}],
            }
        ],
    }
    assert _extract_output_text(payload) == raw


def test_openai_status_requires_server_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert openai_prefill_status().available is False
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENAI_PREFILL_MODEL", "gpt-5-mini")
    status = openai_prefill_status()
    assert status.available is True
    assert status.model == "gpt-5-mini"


def test_review_template_has_one_click_prefill_and_add_another_button():
    template = Path("app/templates/admin_discovery_review.html").read_text(encoding="utf-8")
    assert "AI Prefill All People" in template
    assert "/openai-prefill" in template
    assert "+ Add another missing person from this post" in template
    assert "sessionStorage" in template
    assert "Create All Non-Duplicate People as Pending Entries" in template
    assert "Manual ChatGPT fallback" in template


def test_backend_prefill_endpoint_returns_all_people_without_manual_json(admin_client, monkeypatch):
    admin_client.post(
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
    with SessionLocal() as db:
        db.add(
            DiscoveryCandidate(
                disaster_id=1,
                platform="facebook",
                query="q",
                url="https://facebook.com/example/posts/123",
                title="Two people missing",
                snippet="A Person and B Person are missing in Timure.",
                status="relevant",
            )
        )
        db.commit()

    async def fake_prefill(*args, **kwargs):
        return {
            "people": [
                {
                    "name": "A Person", "name_ne": None, "age": 30, "gender": None,
                    "last_seen_date": None, "last_seen_time": None,
                    "last_seen_location": "Timure", "clothing": None,
                    "identification_details": "Works at example project",
                    "public_contact_number": "9812345678",
                },
                {
                    "name": "B Person", "name_ne": None, "age": 44, "gender": None,
                    "last_seen_date": None, "last_seen_time": None,
                    "last_seen_location": "Timure", "clothing": None,
                    "identification_details": None,
                    "public_contact_number": "9812345678",
                },
            ],
            "source_notes": "Two explicitly named missing people.",
            "model": "gpt-5-mini",
            "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        }

    async def fake_text(url):
        return "A Person and B Person are missing in Timure. Contact 9812345678."

    async def fake_image(url):
        return None

    monkeypatch.setattr("app.routes.admin.generate_openai_candidate_prefill", fake_prefill)
    monkeypatch.setattr("app.routes.admin.discover_public_post_text", fake_text)
    monkeypatch.setattr("app.routes.admin.discover_public_post_image", fake_image)

    response = admin_client.post("/admin/discovery/1/openai-prefill")
    assert response.status_code == 200
    body = response.json()
    assert [person["name"] for person in body["people"]] == ["A Person", "B Person"]
    assert body["model"] == "gpt-5-mini"
