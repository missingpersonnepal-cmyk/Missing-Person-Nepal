from datetime import date

from app.models import Disaster
from app.services.discovery import (
    SearchResult,
    generate_queries,
    is_person_specific_candidate,
)


def disaster():
    return Disaster(
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


def test_named_missing_person_post_is_accepted():
    result = SearchResult(
        url=(
            "https://facebook.com/"
            "memenepalofficial/posts/123"
        ),
        title="Missing Person Please Share - Atul Pathak",
        snippet=(
            "Atul Pathak has been missing since yesterday. "
            "Last seen in Rasuwa."
        ),
    )

    assert is_person_specific_candidate(
        result,
        disaster(),
    )


def test_generic_flood_news_is_rejected():
    result = SearchResult(
        url=(
            "https://facebook.com/"
            "somenewspage/posts/999"
        ),
        title=(
            "Rasuwa Flood Live Update: Hundreds Missing"
        ),
        snippet=(
            "Death toll rises as rescue operations continue. "
            "Hundreds remain missing."
        ),
    )

    assert not is_person_specific_candidate(
        result,
        disaster(),
    )


def test_missing_person_list_is_accepted():
    result = SearchResult(
        url=(
            "https://facebook.com/"
            "community/posts/555"
        ),
        title="Rasuwa Missing Persons List",
        snippet="Names of missing people after the flood.",
    )

    assert is_person_specific_candidate(
        result,
        disaster(),
    )


def test_queries_explicitly_search_for_names_and_lists():
    queries = generate_queries(
        disaster(),
        platform="facebook",
        max_queries=20,
    )

    assert any(
        "missing person name" in query
        for query in queries
    )

    assert any(
        "missing persons list" in query
        for query in queries
    )
