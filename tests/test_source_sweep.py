from datetime import date

from app.database import SessionLocal
from app.models import Disaster, DiscoveryCandidate
from app.services.discovery import (
    SearchResult,
    discover_candidates,
    facebook_source_scope,
    generate_facebook_source_queries,
)


def test_facebook_page_scope_is_extracted_from_post():
    assert (
        facebook_source_scope(
            "https://www.facebook.com/memenepalofficial/posts/1373166858311853/"
        )
        == "memenepalofficial"
    )


def test_facebook_group_scope_is_extracted_from_post():
    assert (
        facebook_source_scope(
            "https://www.facebook.com/groups/rasuwa/posts/999/"
        )
        == "groups/rasuwa"
    )


def test_source_queries_stay_scoped_to_same_facebook_source():
    disaster = Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa\nTimure",
    )

    source_scope = "Bikkigurungofficial"

    queries = generate_facebook_source_queries(
        disaster,
        source_scope,
        max_queries=4,
    )

    assert queries
    assert len(queries) <= 4

    expected_scope = (
        f"site:facebook.com/{source_scope}"
    )

    # Productive-source searches must never escape
    # back into an unrestricted Facebook query.
    assert all(
        query.startswith(expected_scope)
        for query in queries
    )

    assert any(
        "out of contact" in query
        or "last seen" in query
        for query in queries
    )



class SourceSweepProvider:
    def __init__(self):
        self.calls = []

    def run_queries(self, queries):
        self.calls.append(list(queries))

        if len(self.calls) == 1:
            return [
                (
                    queries[0],
                    SearchResult(
                        url=(
                            "https://facebook.com/"
                            "memenepalofficial/posts/111"
                        ),
                        title="Missing Person in Rasuwa",
                        snippet="Example Person is missing in Rasuwa. Please contact 9800000000.",
                    ),
                )
            ]

        return [
            (
                queries[0],
                SearchResult(
                    url=(
                        "https://facebook.com/"
                        "memenepalofficial/posts/222"
                    ),
                    title="Another Missing Person",
                    snippet="Another Person is out of contact in Rasuwa. Please contact 9810000000.",
                ),
            ),
            (
                queries[0],
                SearchResult(
                    url=(
                        "https://facebook.com/"
                        "memenepalofficial/posts/111"
                    ),
                    title="Duplicate original result",
                    snippet="Same URL should not be stored twice",
                ),
            ),
        ]


def test_discovery_sweeps_same_source_and_deduplicates():
    provider = SourceSweepProvider()

    with SessionLocal() as db:
        disaster = Disaster(
            code="RF",
            name="Rasuwa Flood",
            disaster_type="flood",
            start_date=date(2026, 8, 26),
            affected_locations="Rasuwa\nTimure",
        )

        db.add(disaster)
        db.flush()

        added = discover_candidates(
            db,
            disaster,
            platform="facebook",
            provider=provider,
        )

        db.commit()

        rows = db.query(DiscoveryCandidate).all()

        assert added == 2
        assert len(rows) == 2
        assert len(provider.calls) >= 2

        assert any(
            "site:facebook.com/memenepalofficial" in query
            for query in provider.calls[1]
        )
