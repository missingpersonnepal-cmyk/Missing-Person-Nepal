import json
from datetime import date

from app.models import (
    Disaster,
    DiscoveryCandidate,
    MissingPerson,
    Submission,
)

from app.services.ai_review import (
    build_free_ai_review_prompt,
    parse_free_ai_review,
)

from app.services.master_records import (
    apply_submission_to_master,
)

from app.services.source_images import (
    is_allowed_public_image_url,
)


def test_ai_prompt_requests_image_url_without_identity_inference():
    disaster = Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa",
    )

    candidate = DiscoveryCandidate(
        id=10,
        disaster_id=1,
        platform="facebook",
        query="test",
        url=(
            "https://facebook.com/"
            "example/posts/123"
        ),
        title="Missing Person",
        snippet="Named missing person.",
    )

    prompt = build_free_ai_review_prompt(
        disaster,
        [candidate],
    )

    assert "image_url" in prompt
    assert (
        "do not identify"
        in prompt.casefold()
    )


def test_parser_preserves_image_url():
    raw = json.dumps(
        {
            "results": [
                {
                    "candidate_id": 10,
                    "decision": "accept",
                    "confidence": 0.9,
                    "reason": "specific person",
                    "people": [
                        {
                            "name": "Example Person",
                            "image_url": (
                                "https://scontent.xx.fbcdn.net/"
                                "photo.jpg"
                            ),
                        }
                    ],
                }
            ]
        }
    )

    result = parse_free_ai_review(raw)

    assert (
        result[0]["people"][0]["image_url"]
        == (
            "https://scontent.xx.fbcdn.net/"
            "photo.jpg"
        )
    )


def test_only_allowed_meta_image_hosts_are_fetchable():
    assert is_allowed_public_image_url(
        "https://scontent.xx.fbcdn.net/photo.jpg"
    )

    assert is_allowed_public_image_url(
        "https://lookaside.fbsbx.com/photo.jpg"
    )

    assert not is_allowed_public_image_url(
        "http://scontent.xx.fbcdn.net/photo.jpg"
    )

    assert not is_allowed_public_image_url(
        "https://fbcdn.net.evil.example/photo.jpg"
    )

    assert not is_allowed_public_image_url(
        "https://example.com/photo.jpg"
    )


def test_approved_source_image_flows_into_blank_master():
    person = MissingPerson(
        case_number="RF-0001",
        disaster_id=1,
        name="Example Person",
        last_seen_location="Unknown",
        photo_path=None,
    )

    submission = Submission(
        disaster_id=1,
        name="Example Person",
        last_seen_location="Timure",
        photo_path="source-image.jpg",
    )

    updated = apply_submission_to_master(
        person,
        submission,
    )

    assert person.photo_path == "source-image.jpg"
    assert "photo_path" in updated


def test_existing_master_photo_is_never_replaced_automatically():
    person = MissingPerson(
        case_number="RF-0002",
        disaster_id=1,
        name="Example Person",
        last_seen_location="Timure",
        photo_path="verified.jpg",
    )

    submission = Submission(
        disaster_id=1,
        name="Example Person",
        photo_path="new-source.jpg",
    )

    apply_submission_to_master(
        person,
        submission,
    )

    assert person.photo_path == "verified.jpg"
