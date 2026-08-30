from datetime import date
from pathlib import Path

from app.models import Disaster, DiscoveryCandidate
from app.services.candidate_chatgpt_prefill import (
    build_candidate_chatgpt_prefill_prompt,
)


def test_candidate_chatgpt_prefill_prompt_uses_public_text_and_ocr():
    disaster = Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Timure\nRasuwa",
    )
    candidate = DiscoveryCandidate(
        disaster_id=1,
        platform="facebook",
        query="test",
        url="https://facebook.com/example/posts/123",
        title="Person Missing Example Person",
        snippet="Example Person is missing from Timure.",
        status="relevant",
    )

    prompt = build_candidate_chatgpt_prefill_prompt(
        disaster,
        candidate,
        source_post_text=(
            "Example Person, age 31, was last seen at Timure. "
            "Please contact 9812345678."
        ),
        ocr_text="Name: Example Person",
    )

    assert "already marked this public source as RELEVANT" in prompt
    assert "9812345678" in prompt
    assert "Name: Example Person" in prompt
    assert "MULTIPLE missing people" in prompt
    assert "Never identify a person from a photograph" in prompt
    assert '"people"' in prompt
    assert '"public_contact_number"' in prompt


def test_relevant_review_template_has_chatgpt_prefill_workflow():
    template = Path("app/templates/admin_discovery_review.html").read_text(
        encoding="utf-8"
    )

    assert "id=\"chatgpt-prefill\"" in template
    assert "candidate.status == 'relevant'" in template
    assert "Copy ChatGPT Prefill Prompt" in template
    assert "Paste ChatGPT JSON result" in template
    assert "Apply ChatGPT Prefill" in template
    assert "ChatGPT found multiple missing people in this post" in template
    assert "applyAiPerson" in template
    assert "person-identification" in template


def test_mark_relevant_redirects_to_chatgpt_prefill_anchor():
    admin = Path("app/routes/admin.py").read_text(encoding="utf-8")

    assert 'f"/admin/discovery/{candidate_id}#chatgpt-prefill"' in admin
    assert "candidate.status = \"relevant\"" in admin
