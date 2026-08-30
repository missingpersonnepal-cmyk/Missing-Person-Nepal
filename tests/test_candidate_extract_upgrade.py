from datetime import date

from app.models import Disaster, DiscoveryCandidate
from app.services.candidate_extract import extract_candidate_prefill


def event():
    return Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa\nTimure\nBetrawati\nSyafrubesi\nMailung",
    )


def candidate(title, snippet=""):
    return DiscoveryCandidate(
        disaster_id=1,
        platform="facebook",
        query="test",
        url="https://facebook.com/example/posts/123",
        title=title,
        snippet=snippet,
    )


def test_rich_text_prefill_extracts_time_location_and_contacts():
    data = extract_candidate_prefill(
        candidate(
            "Person Missing Rajan Shrestha",
            "Rajan Shrestha, age 41, last seen in Timure, Rasuwa at 8:30 AM. Contact 9841008720.",
        ),
        event(),
    )
    assert data["name"] == "Rajan Shrestha"
    assert data["age"] == 41
    assert data["last_seen_time"] == "08:30"
    assert data["last_seen_location"] == "Timure, Rasuwa"
    assert data["public_contact_number"] == "9841008720"


def test_ocr_nepali_poster_can_supply_structured_fields():
    data = extract_candidate_prefill(
        candidate("Please share"),
        event(),
        ocr_text=(
            "नाम: सुमन मगर\n"
            "उमेर: २१\n"
            "लिङ्ग: पुरुष\n"
            "हराएको स्थान: टिमुरे\n"
            "सम्पर्क: ९८४१००८७२०"
        ),
    )
    assert data["name"] == "सुमन मगर"
    assert data["name_ne"] == "सुमन मगर"
    assert data["age"] == 21
    assert data["gender"] == "Male"
    assert data["last_seen_location"] == "टिमुरे"
    assert data["public_contact_number"] == "9841008720"


def test_gender_is_not_inferred_from_name():
    data = extract_candidate_prefill(candidate("Person Missing Anushka Pandey"), event())
    assert data["gender"] is None
