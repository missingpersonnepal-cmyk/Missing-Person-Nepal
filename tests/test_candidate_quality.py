from datetime import date

from app.models import Disaster
from app.services.discovery import (
    SearchResult,
    is_person_specific_candidate,
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
            "Rasuwagadhi\n"
            "Syabrubesi\n"
            "Gosaikunda\n"
            "Betravati\n"
            "Mailung"
        ),
    )


def test_direct_missing_notice_is_admitted():
    result = SearchResult(
        url="https://facebook.com/publicpage/posts/100",
        title="Person Missing",
        snippet=(
            "Example Person, age 17, is currently out of contact "
            "after travelling in Gosaikunda. "
            "Please contact 9700000000."
        ),
    )

    assert is_person_specific_candidate(
        result,
        event(),
    )


def test_missing_family_notice_is_admitted():
    result = SearchResult(
        url="https://facebook.com/publicpage/posts/101",
        title="Family members missing in Rasuwa",
        snippet=(
            "Parents are missing and cannot be contacted. "
            "If anyone has information please contact 9800000000."
        ),
    )

    assert is_person_specific_candidate(
        result,
        event(),
    )


def test_romanized_nepali_out_of_contact_notice_is_admitted():
    result = SearchResult(
        url="https://facebook.com/publicpage/posts/102",
        title="Rasuwa contact notice",
        snippet=(
            "Example Person hijo 8:40 bata contact ma aaunu "
            "vako xaina. Contact 9740000000."
        ),
    )

    assert is_person_specific_candidate(
        result,
        event(),
    )


def test_missing_person_poster_text_is_admitted():
    result = SearchResult(
        url="https://facebook.com/publicpage/posts/103",
        title="MISSING PERSON - Rasuwa Flood",
        snippet=(
            "Age 32. Working location Timure. Missing since "
            "Rasuwa Flood. If found please contact 9860000000."
        ),
    )

    assert is_person_specific_candidate(
        result,
        event(),
    )


def test_generic_rasuwa_flood_news_is_rejected():
    result = SearchResult(
        url="https://facebook.com/newspage/posts/200",
        title="Floodwaters surged into Mailung in Nepal's Rasuwa district",
        snippet=(
            "Roads and bridges were damaged as rescue operations "
            "continued after floodwaters surged through the area."
        ),
    )

    assert not is_person_specific_candidate(
        result,
        event(),
    )


def test_foreign_missing_group_is_rejected():
    result = SearchResult(
        url="https://facebook.com/groups/texas/posts/300",
        title="Texas Flood 2025 Missing People",
        snippet=(
            "Support group helping locate missing people after "
            "the Texas flood."
        ),
    )

    assert not is_person_specific_candidate(
        result,
        event(),
    )


def test_page_homepage_is_not_a_person_candidate():
    result = SearchResult(
        url="https://facebook.com/somepublicpage",
        title="Some public Facebook page",
        snippet="Rasuwa flood updates",
    )

    assert not is_person_specific_candidate(
        result,
        event(),
    )
