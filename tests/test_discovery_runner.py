from datetime import date

from app.database import SessionLocal
from app.models import Disaster, DiscoveryCandidate
from app.services.discovery import SearchResult, discover_candidates


class FakeProvider:
    def run_queries(self, queries):
        assert queries
        return [
            (
                queries[0],
                SearchResult(
                    url="https://facebook.com/groups/rasuwa/posts/999",
                    title="Missing Person in Rasuwa and Koshi",
                    snippet="Example Person is सम्पर्कविहीन after Rasuwa and Koshi floods. Contact 9800000000.",
                ),
            )
        ]


def test_discovery_runner_persists_public_facebook_candidate():
    with SessionLocal() as db:
        disaster = Disaster(code="RF", name="Rasuwa Flood", disaster_type="flood", start_date=date(2026, 8, 26), affected_locations="Rasuwa")
        db.add(disaster); db.flush()
        added = discover_candidates(db, disaster, platform="facebook", provider=FakeProvider())
        db.commit()
        assert added == 1
        row = db.query(DiscoveryCandidate).one()
        assert "facebook.com" in row.url


def test_same_public_url_can_be_relevant_to_different_disasters():
    with SessionLocal() as db:
        first = Disaster(code="RF", name="Rasuwa Flood", disaster_type="flood", start_date=date(2026, 8, 26), affected_locations="Rasuwa")
        second = Disaster(code="KF", name="Koshi Flood", disaster_type="flood", start_date=date(2026, 8, 27), affected_locations="Koshi")
        db.add_all([first, second]); db.flush()
        assert discover_candidates(db, first, platform="facebook", provider=FakeProvider()) == 1
        assert discover_candidates(db, second, platform="facebook", provider=FakeProvider()) == 1
        db.commit()
        assert db.query(DiscoveryCandidate).count() == 2
