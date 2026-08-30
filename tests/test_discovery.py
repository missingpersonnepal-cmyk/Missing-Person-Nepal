from datetime import date

from app.models import Disaster
from app.services.discovery import generate_queries, google_search_url


def test_discovery_queries_include_facebook_location_and_missing_terms():
    disaster = Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa\nTimure",
    )

    queries = generate_queries(
        disaster,
        platform="facebook",
        max_queries=8,
    )

    assert queries

    # Keep a Facebook site-constrained search path.
    assert any(
        "site:facebook.com" in q
        for q in queries
    )

    # Search must still cover the affected locations.
    assert any(
        "Rasuwa" in q
        for q in queries
    )

    # Prefer person-specific language over the old broad
    # "facebook missing person Rasuwa flood" query.
    assert any(
        phrase in q
        for q in queries
        for phrase in (
            "out of contact",
            "last seen",
            "बेपत्ता",
            "सम्पर्कविहीन",
        )
    )

    assert (
        "facebook missing person Rasuwa flood"
        not in queries
    )

    assert google_search_url(
        queries[0]
    ).startswith(
        "https://www.google.com/search?q="
    )



def test_bounded_discovery_run_spreads_across_locations_and_keywords():
    disaster = Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations=(
            "Rasuwa\n"
            "Timure\n"
            "Rasuwagadhi\n"
            "Syabrubesi"
        ),
    )

    queries = generate_queries(
        disaster,
        platform="facebook",
        max_queries=8,
    )

    assert len(queries) == 8

    assert all(
        any(loc in q for q in queries)
        for loc in [
            "Rasuwa",
            "Timure",
            "Rasuwagadhi",
            "Syabrubesi",
        ]
    )

    represented = {
        keyword
        for keyword in (
            "out of contact",
            "last seen",
            "बेपत्ता",
            "सम्पर्कविहीन",
        )
        if any(
            keyword in q
            for q in queries
        )
    }

    assert len(represented) >= 3

