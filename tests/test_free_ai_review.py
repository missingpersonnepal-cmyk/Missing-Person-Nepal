import json
from datetime import date

import pytest

from app.models import Disaster, DiscoveryCandidate
from app.services.ai_review import (
    build_free_ai_review_prompt,
    parse_free_ai_review,
)


def test_free_ai_prompt_contains_candidates_and_safety_rules():
    disaster = Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa\nTimure",
    )

    candidate = DiscoveryCandidate(
        id=17,
        disaster_id=1,
        platform="facebook",
        query="facebook missing person Rasuwa flood",
        url="https://facebook.com/example/posts/123",
        title="Missing Person",
        snippet="Example Person is missing in Timure.",
    )

    prompt = build_free_ai_review_prompt(
        disaster,
        [candidate],
    )

    assert '"candidate_id": 17' in prompt
    assert "general news" in prompt
    assert "Never identify a person from a photograph" in prompt
    assert "MULTIPLE missing people" in prompt


def test_parse_free_ai_review_supports_multiple_people():
    raw = json.dumps(
        {
            "results": [
                {
                    "candidate_id": 17,
                    "decision": "accept",
                    "confidence": 0.91,
                    "reason": "Named missing family",
                    "people": [
                        {"name": "Person One"},
                        {"name": "Person Two"},
                    ],
                }
            ]
        }
    )

    rows = parse_free_ai_review(raw)

    assert len(rows) == 1
    assert rows[0]["candidate_id"] == 17
    assert rows[0]["decision"] == "accept"
    assert len(rows[0]["people"]) == 2


def test_parse_free_ai_review_rejects_non_json():
    with pytest.raises(ValueError):
        parse_free_ai_review("not json")
