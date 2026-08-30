from datetime import date

from app.models import Disaster, DiscoveryCandidate
from app.services.openai_prefill import (
    _build_request_payload,
    _filter_evidence_verified_people,
)
from app.services.source_images import extract_public_post_text_from_html


def _candidate(*, title: str, snippet: str = "") -> DiscoveryCandidate:
    return DiscoveryCandidate(
        id=77,
        disaster_id=1,
        platform="facebook",
        query="test",
        url=(
            "https://www.facebook.com/Bikkigurungofficial/posts/"
            "-person-missingrajesh-shrestha-has-been-out-of-contact/1627733075386545"
        ),
        title=title,
        snippet=snippet,
        status="relevant",
    )


def _disaster() -> Disaster:
    return Disaster(
        code="RF",
        name="Rasuwa Flood",
        disaster_type="flood",
        start_date=date(2026, 8, 26),
        affected_locations="Rasuwa\nTimure",
    )


def test_rajesh_post_rejects_page_author_as_second_missing_person():
    candidate = _candidate(
        title=(
            "PERSON MISSING Rajesh Shrestha has been out of contact "
            "since yesterday morning"
        ),
        snippet="Rajesh Shrestha has been out of contact since yesterday morning.",
    )
    contaminated_public_text = (
        "Bikki Gurung | PERSON MISSING Rajesh Shrestha has been out of contact "
        "since yesterday morning. Please help find him."
    )
    raw = {
        "people": [
            {
                "name": "Rajesh Shrestha",
                "name_ne": None,
                "age": None,
                "gender": None,
                "last_seen_date": None,
                "last_seen_time": None,
                "last_seen_location": None,
                "clothing": None,
                "identification_details": None,
                "public_contact_number": None,
                "evidence_source": "title",
                "missing_status_evidence": candidate.title,
            },
            {
                "name": "Bikki Gurung",
                "name_ne": None,
                "age": None,
                "gender": None,
                "last_seen_date": None,
                "last_seen_time": None,
                "last_seen_location": None,
                "clothing": None,
                "identification_details": None,
                "public_contact_number": None,
                "evidence_source": "public_post_text",
                "missing_status_evidence": contaminated_public_text,
            },
        ],
        "source_notes": None,
    }

    verified, rejected = _filter_evidence_verified_people(
        raw,
        candidate,
        source_post_text=contaminated_public_text,
        ocr_text="",
    )

    assert [person["name"] for person in verified["people"]] == ["Rajesh Shrestha"]
    assert any("Bikki Gurung" in reason for reason in rejected)


def test_genuine_two_person_missing_list_still_passes():
    title = "Missing persons: A Person, B Person"
    candidate = _candidate(title=title)
    raw_people = []
    for name in ("A Person", "B Person"):
        raw_people.append(
            {
                "name": name,
                "name_ne": None,
                "age": None,
                "gender": None,
                "last_seen_date": None,
                "last_seen_time": None,
                "last_seen_location": "Timure",
                "clothing": None,
                "identification_details": None,
                "public_contact_number": None,
                "evidence_source": "title",
                "missing_status_evidence": title,
            }
        )

    verified, rejected = _filter_evidence_verified_people(
        {"people": raw_people, "source_notes": None},
        candidate,
        source_post_text="",
        ocr_text="",
    )

    assert [person["name"] for person in verified["people"]] == ["A Person", "B Person"]
    assert rejected == []


def test_contact_person_is_not_admitted_without_direct_missing_status():
    candidate = _candidate(
        title="Missing person Rajesh Shrestha",
        snippet="Rajesh Shrestha is missing. Contact Suman Shrestha at 9800000000.",
    )
    raw = {
        "people": [
            {
                "name": "Rajesh Shrestha",
                "name_ne": None,
                "age": None,
                "gender": None,
                "last_seen_date": None,
                "last_seen_time": None,
                "last_seen_location": None,
                "clothing": None,
                "identification_details": None,
                "public_contact_number": "9800000000",
                "evidence_source": "indexed_snippet",
                "missing_status_evidence": "Rajesh Shrestha is missing.",
            },
            {
                "name": "Suman Shrestha",
                "name_ne": None,
                "age": None,
                "gender": None,
                "last_seen_date": None,
                "last_seen_time": None,
                "last_seen_location": None,
                "clothing": None,
                "identification_details": "Contact person",
                "public_contact_number": "9800000000",
                "evidence_source": "indexed_snippet",
                "missing_status_evidence": "Contact Suman Shrestha at 9800000000.",
            },
        ],
        "source_notes": None,
    }

    verified, rejected = _filter_evidence_verified_people(
        raw,
        candidate,
        source_post_text="",
        ocr_text="",
    )
    assert [person["name"] for person in verified["people"]] == ["Rajesh Shrestha"]
    assert any("Suman Shrestha" in reason for reason in rejected)


def test_public_post_text_does_not_choose_long_unrelated_json_ld_over_meta():
    html = """
    <html><head>
      <meta property="og:description"
        content="PERSON MISSING Rajesh Shrestha has been out of contact since yesterday morning.">
      <script type="application/ld+json">
      {
        "@type":"WebPage",
        "mainEntity": {
          "@type":"Article",
          "description":"Unrelated recommended item naming Another Person and several other people."
        }
      }
      </script>
    </head></html>
    """
    text = extract_public_post_text_from_html(html)
    assert text == "PERSON MISSING Rajesh Shrestha has been out of contact since yesterday morning."
    assert "Another Person" not in text


def test_openai_schema_requires_per_person_missing_evidence():
    payload = _build_request_payload(
        _disaster(),
        _candidate(title="Missing person Rajesh Shrestha"),
        model="gpt-5.6-luna",
    )
    person_schema = payload["text"]["format"]["schema"]["properties"]["people"]["items"]
    assert "evidence_source" in person_schema["required"]
    assert "missing_status_evidence" in person_schema["required"]
    assert "Facebook/page/profile/post author" in payload["instructions"]
    assert "Where does the source explicitly say THIS person is missing?" in payload["instructions"]
