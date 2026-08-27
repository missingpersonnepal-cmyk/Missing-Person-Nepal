from datetime import date

from app.models import Disaster
from app.services.discovery import generate_queries, google_search_url


def test_discovery_queries_include_facebook_location_and_missing_terms():
    disaster = Disaster(code="RF", name="Rasuwa Flood", disaster_type="flood", start_date=date(2026, 8, 26), affected_locations="Rasuwa\nTimure")
    queries = generate_queries(disaster, platform="facebook", max_queries=8)
    assert queries
    assert all("site:facebook.com" in q for q in queries)
    assert any("Rasuwa" in q for q in queries)
    assert any("सम्पर्कविहीन" in q or "बेपत्ता" in q for q in queries)
    assert google_search_url(queries[0]).startswith("https://www.google.com/search?q=")


def test_bounded_discovery_run_spreads_across_locations_and_keywords():
    disaster = Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa\nTimure\nRasuwagadhi\nSyabrubesi",
    )
    queries = generate_queries(disaster, platform="facebook", max_queries=8)
    assert len(queries) == 8
    assert all(any(loc in q for q in queries) for loc in ["Rasuwa", "Timure", "Rasuwagadhi", "Syabrubesi"])
    # More than one missing-person phrase should be represented in a short run.
    represented = {kw for kw in ("सम्पर्कविहीन", "सम्पर्क विहीन", "बेपत्ता", "हराएको") if any(kw in q for q in queries)}
    assert len(represented) >= 3
