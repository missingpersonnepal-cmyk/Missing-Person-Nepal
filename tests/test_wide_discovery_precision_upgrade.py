from datetime import date

from app.models import Disaster
from app.services.wide_discovery import WIDE_MAX_QUERIES, generate_wide_queries


def event():
    return Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa\nTimure\nBetrawati\nSyafrubesi\nMailung",
    )


def test_wide_plan_is_bounded_and_date_scoped():
    queries = generate_wide_queries(event(), source_scopes=["Bikkigurungofficial"])
    assert len(queries) <= WIDE_MAX_QUERIES == 40
    assert queries
    assert all("site:facebook.com" in query for query in queries)
    assert all("after:2026-08-25" in query for query in queries)


def test_wide_plan_avoids_bare_missing_query():
    queries = generate_wide_queries(event(), source_scopes=[])
    assert all('"missing"' not in query.casefold() for query in queries)
    assert any('"out of contact"' in query.casefold() for query in queries)
    assert any("सम्पर्कविहीन" in query for query in queries)
