from datetime import date

from app.models import (
    Disaster,
    DiscoveryCandidate,
)

from app.services.candidate_extract import (
    extract_candidate_prefill,
)


def event():
    return Disaster(
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


def row(title, snippet):
    return DiscoveryCandidate(
        disaster_id=1,
        platform="facebook",
        query="test",
        url=(
            "https://facebook.com/"
            "example/posts/123"
        ),
        title=title,
        snippet=snippet,
    )


def test_buddha_sang_ghale_prefill():

    data = extract_candidate_prefill(
        row(
            (
                "Bikki Gurung - Person Missing "
                "Mr. Buddha Sang Ghale"
            ),
            (
                "Person Missing Mr. Buddha Sang Ghale "
                "(49) from Sanima Bank, Timure, Rasuwa. "
                "Please contact 9764770774."
            ),
        ),
        event(),
    )

    assert data["name"] == "Buddha Sang Ghale"
    assert data["age"] == 49
    assert data["last_seen_location"] == "Timure"
    assert data["public_contact_number"] == "9764770774"


def test_anushka_pandey_prefill():

    data = extract_candidate_prefill(
        row(
            "Person Missing Anushka Pandey",
            (
                "Person Missing Anushka Pandey, "
                "who works at Timure Health Post, Rasuwa."
            ),
        ),
        event(),
    )

    assert data["name"] == "Anushka Pandey"
    assert data["last_seen_location"] == "Timure"


def test_shyam_kumar_poudel_prefill():

    data = extract_candidate_prefill(
        row(
            "Person Missing Shyam Kumar Poudel",
            (
                "Person Missing Shyam Kumar Poudel was "
                "last known to be in Timure, "
                "near Ghatte Khola, Rasuwa."
            ),
        ),
        event(),
    )

    assert data["name"] == "Shyam Kumar Poudel"

    # Preserve the explicit public last-known-location wording
    # instead of collapsing it to only the affected-place token.
    assert (
        data["last_seen_location"]
        == "Timure, near Ghatte Khola, Rasuwa"
    )



def test_ravindra_yadav_prefill():

    data = extract_candidate_prefill(
        row(
            "Er Ravindra Yadav सम्पर्कविहीन",
            (
                "Upper Trishuli 3B Hydropower Project, "
                "Betrawati, Nepal"
            ),
        ),
        event(),
    )

    assert data["name"] == "Ravindra Yadav"
    assert data["last_seen_location"] == "Betrawati"
