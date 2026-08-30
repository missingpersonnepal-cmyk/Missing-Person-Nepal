from __future__ import annotations

import time
from datetime import timedelta
from typing import Protocol
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Disaster, DiscoveryCandidate
from .discovery import SearchResult, is_person_specific_candidate
from .normalization import canonicalize_url
from .priority_sources import (
    custom_tag_queries,
    priority_source_scopes,
    priority_wide_queries,
    user_search_tags,
    user_source_seeds,
)
from .search_providers import SerperPublicSearch


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


PRECISION_TERMS = [
    "out of contact",
    "last seen",
    "has been missing",
    "person missing",
    "cannot be contacted",
    "सम्पर्कविहीन",
    "सम्पर्क विहीन",
    "बेपत्ता",
    "खोजिदिनुहोला",
    "हराएको व्यक्ति",
]

LIST_TERMS = [
    "missing persons list",
    "missing people names",
    "named missing people",
    "missing family",
    "बेपत्ता नामावली",
    "सम्पर्कविहीन नाम",
    "हराएका व्यक्तिको सूची",
]

SOURCE_TERMS = [
    "out of contact",
    "last seen",
    "person missing",
    "सम्पर्कविहीन",
    "बेपत्ता",
    "खोजिदिनुहोला",
]


def is_facebook_post_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    host = (parsed.hostname or "").casefold()
    if not (host == "facebook.com" or host.endswith(".facebook.com")):
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
    if not (host == "facebook.com" or host.endswith(".facebook.com")):
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None

    if parts[0].casefold() == "groups" and len(parts) >= 2:
        return f"groups/{parts[1]}"

    blocked = {
        "watch", "reel", "reels", "photo", "photos", "share",
        "story.php", "permalink.php",
    }
    if parts[0].casefold() in blocked:
        return None

    return parts[0]


def _unique(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = " ".join(item.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _round_robin(groups: list[list[str]], max_queries: int) -> list[str]:
    indexes = [0 for _ in groups]
    output: list[str] = []
    seen: set[str] = set()

    while len(output) < max_queries:
        added = False
        for group_index, group in enumerate(groups):
            while indexes[group_index] < len(group):
                query = group[indexes[group_index]]
                indexes[group_index] += 1
                if query in seen:
                    continue
                seen.add(query)
                output.append(query)
                added = True
                break
            if len(output) >= max_queries:
                break
        if not added:
            break

    return output


def generate_wide_queries(
    disaster: Disaster,
    source_scopes: list[str] | None = None,
    custom_tags: list[str] | None = None,
    manual_source_scopes: list[str] | None = None,
    manual_sources: list[tuple[str, str]] | None = None,
    max_queries: int = WIDE_MAX_QUERIES,
) -> list[str]:
    """Generate a bounded, person-focused Facebook search plan.

    Broad standalone ``missing`` searches are intentionally excluded. Every
    query is constrained to Facebook, an event/location, a stronger
    missing-person phrase, and the disaster time window.
    """
    locations = disaster.locations()
    search_places = _unique([disaster.name, *locations])
    event_root = (
        disaster.name.replace("Flood", "").replace("flood", "").strip()
        or disaster.name
    )
    after = (disaster.start_date - timedelta(days=1)).isoformat()
    date_filter = f"after:{after}"

    location_queries: list[str] = []
    for place in search_places:
        for term in PRECISION_TERMS:
            location_queries.append(
                f'site:facebook.com "{place}" "{term}" {date_filter}'
            )

    list_queries: list[str] = []
    for term in LIST_TERMS:
        list_queries.append(
            f'site:facebook.com "{event_root}" "{term}" {date_filter}'
        )

    priority_queries = priority_wide_queries(
        disaster,
        extra_sources=manual_sources,
    )
    custom_queries = custom_tag_queries(
        disaster,
        custom_tags or [],
    )

    source_queries: list[str] = []
    # Research-backed seed sources and human-confirmed productive sources get
    # reserved space. Human-learned scopes remain event-specific.
    seeded_scopes = priority_source_scopes()
    combined_scopes = _unique([
        *(manual_source_scopes or []),
        *(source_scopes or []),
        *seeded_scopes,
    ])

    # Interleave scopes before repeating terms so a small global query budget
    # cannot be monopolized by the first source in the list.
    for term in SOURCE_TERMS:
        for scope in combined_scopes:
            source_queries.append(
                f'site:facebook.com/{scope} "{event_root}" "{term}" {date_filter}'
            )
    for place in locations[:4]:
        for term in ("out of contact", "सम्पर्कविहीन", "बेपत्ता"):
            for scope in combined_scopes:
                source_queries.append(
                    f'site:facebook.com/{scope} "{place}" "{term}" {date_filter}'
                )

    location_queries = _unique(location_queries)
    list_queries = _unique(list_queries)
    source_queries = _unique(source_queries)
    priority_queries = _unique(priority_queries)
    custom_queries = _unique(custom_queries)

    # User-added search phrases and sources receive guaranteed lanes.
    # still dominate the bounded plan. The hard cap is never exceeded.
    return _round_robin(
        [
            custom_queries,
            priority_queries,
            location_queries,
            source_queries,
            location_queries,
            list_queries,
        ],
        max_queries,
    )


def collect_known_source_scopes(
    db: Session,
    disaster_id: int,
    limit: int = 30,
) -> list[str]:
    """Return source scopes promoted by human/processed relevance.

    Repeated relevant posts rank ahead of one-off sources. This lets the
    discovery engine learn new high-output sharers without trusting raw,
    unreviewed search results.
    """
    urls = list(
        db.scalars(
            select(DiscoveryCandidate.url)
            .where(
                DiscoveryCandidate.disaster_id == disaster_id,
                DiscoveryCandidate.status.in_(["relevant", "reviewed"]),
            )
            .order_by(DiscoveryCandidate.found_at.desc())
            .limit(1000)
        ).all()
    )

    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}

    for index, url in enumerate(urls):
        scope = facebook_source_scope(url)
        if not scope:
            continue
        counts[scope] = counts.get(scope, 0) + 1
        first_seen.setdefault(scope, index)

    ranked = sorted(
        counts,
        key=lambda scope: (
            -counts[scope],
            first_seen[scope],
            scope.casefold(),
        ),
    )
    return ranked[:limit]


def _is_source_scoped_query(query: str) -> bool:
    prefix = "site:facebook.com/"
    return query.casefold().startswith(prefix) and not query.casefold().startswith(
        "site:facebook.com \"")


def run_wide_discovery(
    db: Session,
    disaster: Disaster,
    provider: SearchProvider | None = None,
    max_queries: int = WIDE_MAX_QUERIES,
    request_delay_seconds: float = WIDE_REQUEST_DELAY_SECONDS,
) -> dict[str, int]:
    provider = provider or SerperPublicSearch()

    scopes = collect_known_source_scopes(db, disaster.id)
    tag_rows = user_search_tags(db, disaster.id, "facebook")
    source_rows = user_source_seeds(db, disaster.id, "facebook")
    queries = generate_wide_queries(
        disaster,
        source_scopes=scopes,
        custom_tags=[row.tag for row in tag_rows],
        manual_source_scopes=[row.scope for row in source_rows],
        manual_sources=[(row.label, row.scope) for row in source_rows],
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
            url = canonicalize_url(result.url)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            if not is_facebook_post_url(url):
                continue

            normalized_result = SearchResult(
                url=url,
                title=result.title,
                snippet=result.snippet,
            )

            # Normal searches require explicit event context in the indexed
            # text. Human-confirmed source sweeps may omit it, but still need
            # strong person-level evidence.
            if not is_person_specific_candidate(
                normalized_result,
                disaster,
                require_event_context=not _is_source_scoped_query(query),
            ):
                continue

            existing = db.scalar(
                select(DiscoveryCandidate.id).where(
                    DiscoveryCandidate.disaster_id == disaster.id,
                    DiscoveryCandidate.url == url,
                )
            )
            if existing:
                continue

            db.add(
                DiscoveryCandidate(
                    disaster_id=disaster.id,
                    platform="facebook",
                    query="wide:" + query,
                    url=url,
                    title=result.title,
                    snippet=result.snippet,
                    status="needs_ai",
                )
            )
            accepted_for_ai += 1

        if request_delay_seconds > 0 and index < len(queries) - 1:
            time.sleep(request_delay_seconds)

    return {
        "queries": searched,
        "raw_results": raw_results,
        "needs_ai": accepted_for_ai,
    }
