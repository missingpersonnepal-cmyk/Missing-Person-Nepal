from datetime import date

from app.models import Disaster
from app.services.wide_discovery import (
    generate_wide_queries,
)


def test_wide_queries_mix_locations_lists_and_sources():

    disaster = Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations=(
            "Rasuwa\n"
            "Timure\n"
            "Syafrubesi\n"
            "Mailung\n"
            "Betrawati\n"
            "Trishuli Bazaar\n"
            "Galchhi"
        ),
    )

    queries = generate_wide_queries(
        disaster,
        source_scopes=[
            "bikki.gurung",
            "memenepalofficial",
        ],
        max_queries=96,
    )

    assert len(queries) == 96

    assert any(
        '"Timure"' in query
        for query in queries
    )

    assert any(
        "missing persons list" in query
        for query in queries
    )

    assert any(
        "site:facebook.com/bikki.gurung"
        in query
        for query in queries
    )

    assert any(
        "बेपत्ता" in query
        or "सम्पर्कविहीन" in query
        for query in queries
    )


def test_small_budget_is_still_balanced():

    disaster = Disaster(
        code="RF2",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa\nTimure",
    )

    queries = generate_wide_queries(
        disaster,
        source_scopes=[
            "bikki.gurung",
        ],
        max_queries=12,
    )

    assert len(queries) == 12

    assert any(
        "site:facebook.com/bikki.gurung"
        in query
        for query in queries
    )

    assert any(
        "missing persons list" in query
        for query in queries
    )
