from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import settings
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Disaster, DiscoveryCandidate
from .normalization import canonicalize_url, location_terms

NEPALI_KEYWORDS = [
    "सम्पर्कविहीन",
    "सम्पर्क विहीन",
    "बेपत्ता",
    "हराएको",
    "हराइरहेको",
    "खोजिदिनुहोला",
    "सम्पर्क गर्नुहोला",
]
ENGLISH_KEYWORDS = [
    "missing person",
    "missing",
    "out of contact",
    "unaccounted for",
    "please help find",
    "last seen",
]

PLATFORM_SITE_FILTERS = {
    "facebook": "site:facebook.com",
    "instagram": "site:instagram.com",
    "tiktok": "site:tiktok.com",
    "x": "site:x.com",
    "reddit": "site:reddit.com",
    "web": "",
}


@dataclass(slots=True)
class SearchResult:
    url: str
    title: str
    snippet: str


def generate_queries(disaster: Disaster, platform: str = "facebook", max_queries: int | None = None) -> list[str]:
    max_queries = max_queries or settings.discovery_max_queries_per_run
    locations = disaster.locations() or [disaster.name]
    site = PLATFORM_SITE_FILTERS.get(platform, PLATFORM_SITE_FILTERS["facebook"])
    queries: list[str] = []
    keywords = NEPALI_KEYWORDS + ENGLISH_KEYWORDS
    # Round-robin the location/keyword matrix. A bounded V0 run should cover both
    # several affected places and several Nepali/English missing-person phrases,
    # rather than exhausting the budget on one location or one keyword.
    seen_pairs: set[tuple[str, str]] = set()
    rounds = max(len(locations), len(keywords))
    for offset in range(rounds):
        for location_index, location in enumerate(locations):
            keyword = keywords[(location_index + offset) % len(keywords)]
            pair = (location, keyword)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            query = " ".join(
                part
                for part in [site, f'"{location}"', f'"{keyword}"', "Nepal", disaster.disaster_type, str(disaster.start_date.year)]
                if part
            )
            queries.append(query)
            if len(queries) >= max_queries:
                return queries
    return queries


def google_search_url(query: str, start_date: date | None = None, window_days: int = 7) -> str:
    if start_date is not None:
        before = start_date + timedelta(days=max(window_days, 1))
        query = f"{query} after:{start_date.isoformat()} before:{before.isoformat()}"
    return f"https://www.google.com/search?q={quote_plus(query)}"


def _decode_ddg_url(href: str) -> str:
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


class DuckDuckGoPublicSearch:
    """Zero-cost public web search helper.

    This intentionally uses only public search results and never logs in to Facebook,
    bypasses access controls, or accesses closed/private groups. It is best-effort:
    search engines and Facebook indexing can change without notice.
    """

    endpoint = "https://html.duckduckgo.com/html/"

    def __init__(self) -> None:
        self.client = httpx.Client(
            timeout=settings.discovery_timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": "MissingPersonHub/0.1 (+public-disaster-information-discovery; admin-reviewed)"
            },
        )

    def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        limit = max_results or settings.discovery_results_per_query
        response = self.client.post(self.endpoint, data={"q": query})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results: list[SearchResult] = []
        for result in soup.select(".result"):
            anchor = result.select_one(".result__a")
            if anchor is None:
                continue
            href = _decode_ddg_url(anchor.get("href", ""))
            if not href.startswith("http"):
                continue
            snippet_node = result.select_one(".result__snippet")
            results.append(
                SearchResult(
                    url=canonicalize_url(href),
                    title=anchor.get_text(" ", strip=True),
                    snippet=snippet_node.get_text(" ", strip=True) if snippet_node else "",
                )
            )
            if len(results) >= limit:
                break
        return results

    def run_queries(self, queries: list[str]) -> list[tuple[str, SearchResult]]:
        found: list[tuple[str, SearchResult]] = []
        seen: set[str] = set()
        for index, query in enumerate(queries[: settings.discovery_max_queries_per_run]):
            try:
                for result in self.search(query):
                    if result.url and result.url not in seen:
                        seen.add(result.url)
                        found.append((query, result))
            except httpx.HTTPError:
                # Discovery is intentionally fail-soft; manual URL intake remains available.
                continue
            if index < len(queries) - 1:
                time.sleep(settings.discovery_request_delay_seconds)
        return found


def discover_candidates(
    db: Session,
    disaster: Disaster,
    platform: str = "facebook",
    provider: DuckDuckGoPublicSearch | None = None,
) -> int:
    """Run a bounded public-web discovery pass and persist new candidate URLs."""
    provider = provider or DuckDuckGoPublicSearch()
    queries = generate_queries(disaster, platform=platform)
    results = provider.run_queries(queries)
    added = 0
    for query, result in results:
        if platform != "web" and f"{platform}.com" not in result.url and not (
            platform == "x" and "x.com" in result.url
        ):
            continue
        exists = db.scalar(
            select(DiscoveryCandidate.id).where(
                DiscoveryCandidate.disaster_id == disaster.id, DiscoveryCandidate.url == result.url
            )
        )
        if exists:
            continue
        db.add(
            DiscoveryCandidate(
                disaster_id=disaster.id,
                platform=platform,
                query=query,
                url=result.url,
                title=result.title,
                snippet=result.snippet,
            )
        )
        added += 1
    return added
