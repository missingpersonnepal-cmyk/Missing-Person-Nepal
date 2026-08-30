from app.database import SessionLocal
from app.models import DiscoveryCandidate


def test_dashboard_exposes_ordered_operator_workflow(admin_client):
    page = admin_client.get("/admin")
    assert page.status_code == 200
    for label in (
        "Triage new sources",
        "Extract relevant reports",
        "Resolve duplicate sources",
        "Approve submissions",
        "Publish and maintain cases",
    ):
        assert label in page.text


def test_dashboard_counts_duplicate_source_queue(admin_client):
    with SessionLocal() as db:
        db.add(DiscoveryCandidate(
            disaster_id=1,
            platform="facebook",
            query="test",
            url="https://example.com/duplicate",
            title="Exact duplicate source",
            status="possible_duplicate",
        ))
        db.commit()
    page = admin_client.get("/admin")
    assert page.status_code == 200
    assert "1 exact-name matches" in page.text
