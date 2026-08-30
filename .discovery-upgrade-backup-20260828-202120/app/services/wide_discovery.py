from __future__ import annotations
from app.services.search_providers import SerperPublicSearch

import time
from urllib.parse import urlparse
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Disaster, DiscoveryCandidate
from .discovery import SearchResult
from .search_providers import BravePublicSearch
from .normalization import canonicalize_url


class SearchProvider(Protocol):
    def search(
        self,
        query: str,
        max_results: int = 15,
    ) -> list[SearchResult]:
        ...


WIDE_MAX_QUERIES = 40
WIDE_RESULTS_PER_QUERY = 15
WIDE_REQUEST_DELAY_SECONDS = 0.40


WIDE_TERMS = [
    "missing person",
    "missing",
    "out of contact",
    "please help find",
    "please share",
    "missing family",
    "missing persons list",
    "missing people names",
    "सम्पर्कविहीन",
    "सम्पर्क विहीन",
    "बेपत्ता",
    "हराएको",
    "हराइरहेको",
    "बेपत्ता नामावली",
    "सम्पर्कविहीन नाम",
    "हराएको व्यक्ति",
]


MISSING_SIGNALS = [
    "missing person",
    "person missing",
    "has been missing",
    "is missing",
    "missing since",
    "out of contact",
    "cannot be contacted",
    "unable to contact",
    "please help find",
    "please share",
    "सम्पर्कविहीन",
    "सम्पर्क विहीन",
    "बेपत्ता",
    "हराएको",
    "हराइरहेको",
    "खोजिदिनुहोला",
]


def is_facebook_post_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    host = (parsed.hostname or "").casefold()

    if not (
        host == "facebook.com"
        or host.endswith(".facebook.com")
    ):
        return False

    path = parsed.path.casefold()

    return (
        "/posts/" in path
        or "/groups/" in path and "/posts/" in path
        or "permalink.php" in path
        or "story.php" in path
        or "/photos/" in path
        or "/photo/" in path
        or "/reel/" in path
        or "/reels/" in path
        or "/share/p/" in path
        or "/share/v/" in path
    )


def facebook_source_scope(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    host = (parsed.hostname or "").casefold()

    if not (
        host == "facebook.com"
        or host.endswith(".facebook.com")
    ):
        return None

    parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]

    if not parts:
        return None

    if (
        parts[0].casefold() == "groups"
        and len(parts) >= 2
    ):
        return f"groups/{parts[1]}"

    blocked = {
        "watch",
        "reel",
        "reels",
        "photo",
        "photos",
        "share",
        "story.php",
        "permalink.php",
    }

    if parts[0].casefold() in blocked:
        return None

    return parts[0]


def _unique(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()

    for item in items:
        normalized = " ".join(item.split())

        if (
            not normalized
            or normalized in seen
        ):
            continue

        seen.add(normalized)
        output.append(normalized)

    return output


def generate_wide_queries(
    disaster: Disaster,
    source_scopes: list[str] | None = None,
    max_queries: int = WIDE_MAX_QUERIES,
) -> list[str]:
    """Generate a balanced high-recall Facebook search plan.

    The query budget is shared between:
    - affected-location searches;
    - event-wide family/list searches;
    - already productive Facebook sources.

    This prevents one category from consuming the full budget.
    """

    locations = disaster.locations()

    search_places = _unique(
        [
            disaster.name,
            *locations,
        ]
    )

    event_root = (
        disaster.name
        .replace("Flood", "")
        .replace("flood", "")
        .strip()
    )

    location_queries: list[str] = []

    priority_terms = [
        "missing person",
        "missing",
        "out of contact",
        "please help find",
        "सम्पर्कविहीन",
        "सम्पर्क विहीन",
        "बेपत्ता",
        "हराएको",
        "हराइरहेको",
    ]

    for place in search_places:
        for term in priority_terms:
            location_queries.extend(
                [
                    (
                        f'site:facebook.com '
                        f'"{place}" "{term}"'
                    ),
                    (
                        f'facebook '
                        f'"{place}" "{term}"'
                    ),
                ]
            )

    list_queries: list[str] = []

    list_terms = [
        "missing persons list",
        "missing people names",
        "missing family",
        "missing parents",
        "missing son",
        "missing daughter",
        "please share missing person",
        "please help find",
        "contact number missing",
        "people out of contact",
        "unaccounted for",
        "बेपत्ता नामावली",
        "सम्पर्कविहीन नाम",
        "हराएको व्यक्ति",
        "खोजिदिनुहोला",
    ]

    for term in list_terms:
        list_queries.extend(
            [
                (
                    f'site:facebook.com '
                    f'"{event_root}" "{term}"'
                ),
                (
                    f'facebook '
                    f'"{event_root}" "{term}"'
                ),
            ]
        )

    source_queries: list[str] = []

    for scope in source_scopes or []:

        source_queries.extend(
            [
                (
                    f'site:facebook.com/{scope} '
                    f'"{event_root}" missing'
                ),
                (
                    f'site:facebook.com/{scope} '
                    f'"{event_root}" "missing person"'
                ),
                (
                    f'site:facebook.com/{scope} '
                    f'"{event_root}" बेपत्ता'
                ),
                (
                    f'site:facebook.com/{scope} '
                    f'"{event_root}" सम्पर्कविहीन'
                ),
                (
                    f'site:facebook.com/{scope} '
                    f'"{event_root}" "out of contact"'
                ),
            ]
        )

        for place in locations:
            source_queries.extend(
                [
                    (
                        f'site:facebook.com/{scope} '
                        f'"{place}" missing'
                    ),
                    (
                        f'site:facebook.com/{scope} '
                        f'"{place}" बेपत्ता'
                    ),
                    (
                        f'site:facebook.com/{scope} '
                        f'"{place}" सम्पर्कविहीन'
                    ),
                ]
            )

    location_queries = _unique(
        location_queries
    )

    list_queries = _unique(
        list_queries
    )

    source_queries = _unique(
        source_queries
    )

    # Weighted round-robin:
    #
    # location -> source -> location -> list
    #
    # Locations remain the largest category, but known sources
    # and list/family queries are guaranteed space in the run.

    groups = [
        location_queries,
        source_queries,
        location_queries,
        list_queries,
    ]

    indexes = {
        id(location_queries): 0,
        id(source_queries): 0,
        id(list_queries): 0,
    }

    queries: list[str] = []
    seen: set[str] = set()

    while len(queries) < max_queries:

        added_this_round = False

        for group in groups:

            key = id(group)
            index = indexes[key]

            while index < len(group):
                query = group[index]
                index += 1

                if query in seen:
                    continue

                seen.add(query)
                queries.append(query)
                added_this_round = True
                break

            indexes[key] = index

            if len(queries) >= max_queries:
                break

        if not added_this_round:
            break

    return queries


def collect_known_source_scopes(
    db: Session,
    disaster_id: int,
    limit: int = 30,
) -> list[str]:

    urls = list(
        db.scalars(
            select(DiscoveryCandidate.url)
            .where(
                DiscoveryCandidate.disaster_id
                == disaster_id
            )
            .order_by(
                DiscoveryCandidate.found_at.desc()
            )
            .limit(500)
        ).all()
    )

    scopes: list[str] = []

    for url in urls:
        scope = facebook_source_scope(url)

        if scope and scope not in scopes:
            scopes.append(scope)

        if len(scopes) >= limit:
            break

    return scopes


def has_missing_signal(
    title: str,
    snippet: str,
) -> bool:

    text = (
        f"{title} {snippet}"
    ).casefold()

    return any(
        term.casefold() in text
        for term in MISSING_SIGNALS
    )


def run_wide_discovery(
    db: Session,
    disaster: Disaster,
    provider: SearchProvider | None = None,
    max_queries: int = WIDE_MAX_QUERIES,
    request_delay_seconds: float = WIDE_REQUEST_DELAY_SECONDS,
) -> dict[str, int]:

    provider = (
        provider
        or SerperPublicSearch()
    )

    scopes = collect_known_source_scopes(
        db,
        disaster.id,
    )

    queries = generate_wide_queries(
        disaster,
        source_scopes=scopes,
        max_queries=max_queries,
    )

    searched = 0
    raw_results = 0
    accepted_for_ai = 0

    seen_urls: set[str] = set()

    for index, query in enumerate(queries):
        searched += 1

        try:
            results = provider.search(
                query,
                max_results=WIDE_RESULTS_PER_QUERY,
            )
        except httpx.HTTPError:
            continue

        for result in results:
            raw_results += 1

            url = canonicalize_url(
                result.url
            )

            if not url:
                continue

            if url in seen_urls:
                continue

            seen_urls.add(url)

            if not is_facebook_post_url(url):
                continue

            if not has_missing_signal(
                result.title,
                result.snippet,
            ):
                continue

            existing = db.scalar(
                select(
                    DiscoveryCandidate.id
                ).where(
                    DiscoveryCandidate.disaster_id
                    == disaster.id,
                    DiscoveryCandidate.url
                    == url,
                )
            )

            if existing:
                continue

            db.add(
                DiscoveryCandidate(
                    disaster_id=disaster.id,
                    platform="facebook",
                    query=(
                        "wide:"
                        + query
                    ),
                    url=url,
                    title=result.title,
                    snippet=result.snippet,
                    status="needs_ai",
                )
            )

            accepted_for_ai += 1

        if (
            request_delay_seconds > 0
            and index < len(queries) - 1
        ):
            time.sleep(
                request_delay_seconds
            )

    return {
        "queries": searched,
        "raw_results": raw_results,
        "needs_ai": accepted_for_ai,
    }
