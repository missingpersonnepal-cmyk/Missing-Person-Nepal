from __future__ import annotations

import re
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


def generate_queries(
    disaster: Disaster,
    platform: str = "facebook",
    max_queries: int | None = None,
) -> list[str]:
    """Generate bounded discovery searches.

    Facebook discovery deliberately mixes:
      - normal human-style searches
      - site-constrained searches
      - English
      - Nepali
      - high-precision name/list searches

    The relevance gate later decides whether a result is actually
    a missing-person notice.
    """
    max_queries = (
        max_queries
        or settings.discovery_max_queries_per_run
    )

    locations = (
        disaster.locations()
        or [disaster.name]
    )

    queries: list[str] = []
    seen: set[str] = set()

    def add(query: str) -> bool:
        query = query.strip()

        if not query or query in seen:
            return False

        seen.add(query)
        queries.append(query)

        return len(queries) >= max_queries

    if platform == "facebook":

        # ----------------------------------------------------
        # PASS 1
        #
        # Reproduce natural searches while spreading different
        # missing-person terms across affected locations.
        #
        # Example:
        # facebook missing person Rasuwa flood
        # site:facebook.com Rasuwa missing person flood
        # facebook missing Timure flood
        # facebook बेपत्ता Rasuwagadhi flood
        # ----------------------------------------------------

        core_keywords = [
            "out of contact",
            "last seen",
            "बेपत्ता",
            "सम्पर्कविहीन",
        ]

        for index, location in enumerate(locations):
            keyword = core_keywords[
                index % len(core_keywords)
            ]

            if add(
                f"facebook {keyword} "
                f"{location} "
                f"{disaster.disaster_type}"
            ):
                return queries

            if add(
                f"site:facebook.com "
                f"{location} "
                f"{keyword} "
                f"{disaster.disaster_type}"
            ):
                return queries

        # ----------------------------------------------------
        # PASS 2
        #
        # Higher precision searches for names, lists,
        # last-seen notices and direct appeals.
        # ----------------------------------------------------

        precision_phrases = [
            "missing person name",
            "missing persons list",
            "missing people names",
            "missing since last seen",
            "please share missing person",
            "बेपत्ता नामावली",
            "सम्पर्कविहीन नाम",
            "हराएको व्यक्ति",
        ]

        for phrase in precision_phrases:
            for location in locations:

                if add(
                    f"facebook {phrase} "
                    f"{location} "
                    f"{disaster.disaster_type}"
                ):
                    return queries

                if add(
                    f"site:facebook.com "
                    f"{location} "
                    f"{phrase} "
                    f"{disaster.disaster_type}"
                ):
                    return queries

        return queries

    # --------------------------------------------------------
    # OTHER PLATFORMS
    # --------------------------------------------------------

    site = PLATFORM_SITE_FILTERS.get(
        platform,
        "",
    )

    platform_name = (
        "twitter"
        if platform == "x"
        else platform
    )

    keywords = (
        NEPALI_KEYWORDS
        + ENGLISH_KEYWORDS
    )

    for keyword in keywords:
        for location in locations:

            if add(
                " ".join(
                    part
                    for part in [
                        platform_name,
                        keyword,
                        location,
                        disaster.disaster_type,
                    ]
                    if part
                )
            ):
                return queries

            if site:
                if add(
                    f"{site} "
                    f"{location} "
                    f"{keyword} "
                    f"{disaster.disaster_type}"
                ):
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




PERSON_LIST_TERMS = [
    "missing persons list",
    "missing person list",
    "missing people list",
    "list of missing",
    "names of missing",
    "missing people names",
    "missing persons names",
    "नामावली",
    "बेपत्ता सूची",
    "बेपत्ता नाम",
    "हराएका व्यक्तिको सूची",
]

MISSING_TERMS = [
    "missing person",
    "missing",
    "has been missing",
    "missing since",
    "last seen",
    "out of contact",
    "unaccounted for",
    "बेपत्ता",
    "हराएको",
    "हराइरहेको",
    "सम्पर्कविहीन",
    "सम्पर्क विहीन",
]

DIRECT_APPEAL_TERMS = [
    "please share",
    "please help find",
    "help find",
    "if seen",
    "contact if",
    "missing since",
    "last seen",
    "has been missing",
    "खोजिदिनुहोला",
    "सम्पर्क गर्नुहोला",
]

PERSON_CONTEXT_TERMS = [
    "age ",
    "aged ",
    "years old",
    "year old",
    "contact",
    "phone",
    "mobile",
    "resident of",
    "last contacted",
    "last seen",
    "father",
    "mother",
    "son",
    "daughter",
    "उमेर",
    "ठेगाना",
    "सम्पर्क",
    "फोन",
    "मोबाइल",
    "अन्तिम पटक",
]

GENERIC_NEWS_TERMS = [
    "death toll",
    "hundreds missing",
    "people remain missing",
    "hundreds remain missing",
    "rescue operation",
    "rescue operations",
    "live update",
    "latest update",
    "flood update",
    "casualty",
    "casualties",
    "bodies recovered",
    "body recovered",
    "authorities said",
    "government said",
    "breaking news",
]

GENERIC_NAME_WORDS = {
    "missing",
    "person",
    "people",
    "please",
    "share",
    "flood",
    "flash",
    "nepal",
    "news",
    "latest",
    "update",
    "live",
    "death",
    "toll",
    "rescue",
    "facebook",
    "group",
    "official",
}


def is_facebook_url(url: str) -> bool:
    canonical = canonicalize_url(url)

    if not canonical:
        return False

    host = urlparse(canonical).netloc.casefold()

    return (
        host == "facebook.com"
        or host.endswith(".facebook.com")
        or host == "fb.com"
        or host.endswith(".fb.com")
    )


def _has_probable_english_person_name(
    text: str,
    disaster: Disaster,
) -> bool:
    """Best-effort text signal only.

    This does NOT identify anybody from a photograph.
    It only detects name-like text already present in the
    public search result title/snippet.
    """
    blocked = set(GENERIC_NAME_WORDS)

    blocked.add(disaster.disaster_type.casefold())

    for location in disaster.locations():
        for token in location.split():
            blocked.add(token.casefold())

    for token in disaster.name.split():
        blocked.add(token.casefold())

    # Two adjacent capitalized words are a useful signal for
    # English/transliterated personal names such as "Atul Pathak".
    pattern = re.compile(
        r"\b([A-Z][A-Za-z'-]{2,})\s+"
        r"([A-Z][A-Za-z'-]{2,})\b"
    )

    for match in pattern.finditer(text):
        first = match.group(1).casefold()
        second = match.group(2).casefold()

        if first in blocked or second in blocked:
            continue

        return True

    return False


def is_person_specific_candidate(
    result: SearchResult,
    disaster: Disaster,
) -> bool:
    """Admit only person-level/list-level missing results.

    General disaster news is deliberately rejected from the
    missing-person review queue.
    """
    text = f"{result.title or ''} {result.snippet or ''}".strip()

    if not text:
        return False

    folded = text.casefold()

    # A genuine list/name-list is directly useful to this project.
    if any(term.casefold() in folded for term in PERSON_LIST_TERMS):
        return True

    has_missing_signal = any(
        term.casefold() in folded
        for term in MISSING_TERMS
    )

    if not has_missing_signal:
        return False

    has_name = _has_probable_english_person_name(
        text,
        disaster,
    )

    has_direct_appeal = any(
        term.casefold() in folded
        for term in DIRECT_APPEAL_TERMS
    )

    has_person_context = any(
        term.casefold() in folded
        for term in PERSON_CONTEXT_TERMS
    )

    # Nepali notices often expose structured fields rather than
    # English-style capitalization.
    has_nepali_structure = (
        any(
            term in text
            for term in [
                "नाम",
                "उमेर",
                "ठेगाना",
                "सम्पर्क",
                "फोन",
            ]
        )
        and any(
            term in text
            for term in [
                "बेपत्ता",
                "हराएको",
                "सम्पर्कविहीन",
                "सम्पर्क विहीन",
            ]
        )
    )

    news_hits = sum(
        1
        for term in GENERIC_NEWS_TERMS
        if term.casefold() in folded
    )

    # General flood coverage should not enter the queue merely
    # because it contains "hundreds missing".
    if news_hits >= 1 and not (
        has_name
        and (
            has_direct_appeal
            or has_person_context
        )
    ):
        return False

    if has_name and (
        has_direct_appeal
        or has_person_context
        or "missing person" in folded
        or "missing since" in folded
    ):
        return True

    if has_nepali_structure:
        return True

    if has_missing_signal and has_person_context:
        return True

    return False



PHONE_RE = re.compile(r"(?<!\d)(?:\+?977[-\s]?)?(?:9\d[\d\s-]{7,12})(?!\d)")
AGE_RE = re.compile(
    r"\b(?:age[d]?\s*[:\-]?\s*)?(\d{1,2})\s*(?:years?\s*old|year\s*old|yrs?|y/o)\b",
    re.IGNORECASE,
)
NAME_RE = re.compile(
    r"\b([A-Z][A-Za-z'-]{2,})\s+([A-Z][A-Za-z'-]{2,})\b"
)

DIRECT_MISSING_TERMS = [
    "missing person",
    "person missing",
    "has been missing",
    "is missing",
    "missing since",
    "currently missing",
    "out of contact",
    "cannot be contacted",
    "unable to contact",
    "not in contact",
    "contact ma aaunu vako xaina",
    "contact ma aaunu bhako xaina",
    "contact ma aaunu va ko xaina",
    "contact ma aaunu vako chaina",
    "contact ma xaina",
    "contact ma chaina",
    "sampark ma xaina",
    "samparka ma xaina",
    "बेपत्ता",
    "हराएको",
    "हराइरहेको",
    "हराइरहनु",
    "सम्पर्कविहीन",
    "सम्पर्क विहीन",
]

CONTACT_APPEAL_TERMS = [
    "please contact",
    "please share",
    "please help",
    "help find",
    "if you have any information",
    "if anyone has information",
    "if seen",
    "contact:",
    "contact number",
    "call",
    "phone",
    "mobile",
    "सम्पर्क गर्नुहोस्",
    "सम्पर्क गराइदिनुहोस्",
    "सम्पर्क गर्नुहोला",
    "खोजिदिनुहोला",
    "जानकारी भए",
]

LAST_SEEN_TERMS = [
    "last seen",
    "last known location",
    "missing from",
    "missing since",
    "expected to return",
    "last contacted",
    "since yesterday",
    "since today",
    "अन्तिम पटक",
    "देखि सम्पर्क",
]

LIST_TERMS = [
    "missing persons list",
    "missing person list",
    "missing people list",
    "list of missing",
    "names of missing",
    "missing people names",
    "missing persons names",
    "नामावली",
    "बेपत्ता सूची",
    "बेपत्ता नाम",
]

FAMILY_TERMS = [
    "whole family",
    "family missing",
    "parents are missing",
    "parents missing",
    "mother missing",
    "father missing",
    "parents",
    "family members",
    "परिवार",
    "आमा",
    "बुबा",
]

GENERIC_NEWS_TERMS = [
    "death toll",
    "toll rises",
    "hundreds missing",
    "people remain missing",
    "remain missing after",
    "rescue operation",
    "rescue operations",
    "rescue teams",
    "latest update",
    "live update",
    "breaking news",
    "flood update",
    "floodwaters surged",
    "roads and bridges",
    "bridge swept away",
    "bodies recovered",
    "body recovered",
    "authorities said",
    "government said",
    "casualties",
]

GENERIC_NAME_WORDS = {
    "missing",
    "person",
    "people",
    "flood",
    "floods",
    "nepal",
    "rasuwa",
    "facebook",
    "official",
    "news",
    "latest",
    "update",
    "rescue",
    "family",
    "group",
    "support",
    "welcome",
    "texas",
}


def is_facebook_url(url: str) -> bool:
    canonical = canonicalize_url(url)
    if not canonical:
        return False

    host = urlparse(canonical).netloc.casefold()

    return (
        host == "facebook.com"
        or host.endswith(".facebook.com")
        or host == "fb.com"
        or host.endswith(".fb.com")
    )


def is_facebook_post_url(url: str) -> bool:
    """Prefer actual public Facebook content over page/group homepages."""
    canonical = canonicalize_url(url)

    if not canonical or not is_facebook_url(canonical):
        return False

    parsed = urlparse(canonical)
    path = parsed.path.casefold()

    if "/posts/" in path:
        return True

    if path.startswith("/groups/") and "/posts/" in path:
        return True

    if "permalink.php" in path:
        return True

    if "story.php" in path:
        return True

    if "/reel/" in path or "/reels/" in path:
        return True

    if "/photo" in path or "/photos/" in path:
        return True

    if "/share/p/" in path or "/share/v/" in path:
        return True

    return False


def _contains(text: str, terms: list[str]) -> bool:
    folded = text.casefold()
    return any(term.casefold() in folded for term in terms)


def _has_probable_name(text: str, disaster: Disaster) -> bool:
    blocked = set(GENERIC_NAME_WORDS)

    for token in disaster.name.split():
        blocked.add(token.casefold())

    for location in disaster.locations():
        for token in location.split():
            blocked.add(token.casefold())

    for match in NAME_RE.finditer(text):
        first = match.group(1).casefold()
        second = match.group(2).casefold()

        if first in blocked or second in blocked:
            continue

        return True

    return False


def _has_event_context(text: str, disaster: Disaster) -> bool:
    folded = text.casefold()

    event_terms = [
        disaster.name,
        disaster.disaster_type,
        "Nepal",
        "Nepali",
        "Kathmandu",
    ]

    event_terms.extend(disaster.locations())

    # Avoid accepting an unrelated foreign result just because
    # the search query itself mentioned Rasuwa.
    return any(
        term and term.casefold() in folded
        for term in event_terms
    )


def facebook_person_notice_score(
    result: SearchResult,
    disaster: Disaster,
) -> tuple[int, list[str]]:
    """Score only text already present in the public search result.

    Photos are never used to identify a person.
    """
    text = f"{result.title or ''} {result.snippet or ''}".strip()

    if not text:
        return 0, ["empty"]

    score = 0
    reasons: list[str] = []

    if _contains(text, DIRECT_MISSING_TERMS):
        score += 4
        reasons.append("direct-missing-language")

    if _contains(text, LIST_TERMS):
        score += 6
        reasons.append("missing-person-list")

    if PHONE_RE.search(text):
        score += 4
        reasons.append("contact-number")

    if AGE_RE.search(text):
        score += 2
        reasons.append("age")

    if _contains(text, CONTACT_APPEAL_TERMS):
        score += 2
        reasons.append("contact-appeal")

    if _contains(text, LAST_SEEN_TERMS):
        score += 2
        reasons.append("last-seen-or-since")

    if _contains(text, FAMILY_TERMS):
        score += 2
        reasons.append("family-specific")

    if _has_probable_name(text, disaster):
        score += 3
        reasons.append("name-like-text")

    news_hits = sum(
        1
        for term in GENERIC_NEWS_TERMS
        if term.casefold() in text.casefold()
    )

    if news_hits:
        score -= 5 * news_hits
        reasons.append(f"generic-news-{news_hits}")

    return score, reasons


def is_person_specific_candidate(
    result: SearchResult,
    disaster: Disaster,
    *,
    require_event_context: bool = True,
) -> bool:
    if not is_facebook_post_url(result.url):
        return False

    text = f"{result.title or ''} {result.snippet or ''}".strip()

    if require_event_context and not _has_event_context(
        text,
        disaster,
    ):
        return False

    score, _ = facebook_person_notice_score(
        result,
        disaster,
    )

    # Require person-level evidence, not merely the word "missing".
    has_structured_person_evidence = (
        PHONE_RE.search(text) is not None
        or AGE_RE.search(text) is not None
        or _contains(text, CONTACT_APPEAL_TERMS)
        or _contains(text, LAST_SEEN_TERMS)
        or _contains(text, LIST_TERMS)
        or _has_probable_name(text, disaster)
        or _contains(text, FAMILY_TERMS)
    )

    return score >= 6 and has_structured_person_evidence


def auto_triage_candidate_status(
    result: SearchResult,
    disaster: Disaster,
    platform: str,
) -> str:
    """Lightweight automated relevance triage for discovery ingest.

    Strong person-level signals go straight to Relevant so operators can
    focus on the best candidates first. We keep weaker evidence in the
    review flow for a human check.
    """
    if platform != "facebook":
        return "new"

    if not is_person_specific_candidate(result, disaster, require_event_context=True):
        return "new"

    score, reasons = facebook_person_notice_score(result, disaster)

    if score >= 8 and any(reason in reasons for reason in {"list", "missing-person-list", "contact-number", "contact-appeal", "last-seen-or-since"}):
        return "relevant"

    if score >= 6:
        return "needs_ai"

    return "new"


FACEBOOK_SOURCE_SWEEP_MAX_SOURCES = 4
FACEBOOK_SOURCE_SWEEP_QUERIES_PER_SOURCE = 4


def facebook_source_scope(url: str) -> str | None:
    """Return the public Facebook page/group scope for a post URL.

    Examples:
      facebook.com/memenepalofficial/posts/123
          -> memenepalofficial

      facebook.com/groups/rasuwa/posts/456
          -> groups/rasuwa
    """
    canonical = canonicalize_url(url)
    if not canonical:
        return None

    parsed = urlparse(canonical)
    host = parsed.netloc.casefold()

    if not (
        host == "facebook.com"
        or host.endswith(".facebook.com")
        or host == "fb.com"
        or host.endswith(".fb.com")
    ):
        return None

    parts = [
        unquote(part).strip()
        for part in parsed.path.split("/")
        if part.strip()
    ]

    if not parts:
        return None

    first = parts[0].casefold()

    if first == "groups" and len(parts) >= 2:
        return f"groups/{parts[1]}"

    # These URL shapes do not reliably tell us which page/group owns the post.
    unsupported_roots = {
        "watch",
        "reel",
        "reels",
        "share",
        "photo",
        "photos",
        "story.php",
        "permalink.php",
        "plugins",
    }

    if first in unsupported_roots:
        return None

    return parts[0]


def generate_facebook_source_queries(
    disaster: Disaster,
    source_scope: str,
    max_queries: int = FACEBOOK_SOURCE_SWEEP_QUERIES_PER_SOURCE,
) -> list[str]:
    """Search the same public Facebook page/group for more
    person-level missing notices.
    """
    locations = disaster.locations() or [disaster.name]
    site = f"site:facebook.com/{source_scope}"

    templates = [
        "{site} {location} out of contact",
        "{site} {location} last seen",
        "{site} {location} missing persons list",
        "{site} {location} missing people names",
        "{site} {location} बेपत्ता नामावली",
        "{site} {location} सम्पर्कविहीन नाम",
    ]

    queries: list[str] = []
    seen: set[str] = set()

    for template in templates:
        for location in locations:
            query = template.format(
                site=site,
                source=source_scope,
                location=location,
            ).strip()

            if query in seen:
                continue

            seen.add(query)
            queries.append(query)

            if len(queries) >= max_queries:
                return queries

    return queries

def expand_facebook_sources(
    provider,
    disaster: Disaster,
    seed_results: list[tuple[str, SearchResult]],
) -> list[tuple[str, SearchResult]]:
    """Sweep a few publicly indexed posts from promising Facebook sources."""
    scopes: list[str] = []
    seen_scopes: set[str] = set()

    for _, result in seed_results:
        scope = facebook_source_scope(result.url)

        if not scope or scope in seen_scopes:
            continue

        seen_scopes.add(scope)
        scopes.append(scope)

        if len(scopes) >= FACEBOOK_SOURCE_SWEEP_MAX_SOURCES:
            break

    expanded: list[tuple[str, SearchResult]] = []

    for scope in scopes:
        queries = generate_facebook_source_queries(
            disaster,
            scope,
            max_queries=FACEBOOK_SOURCE_SWEEP_QUERIES_PER_SOURCE,
        )

        expanded.extend(provider.run_queries(queries))

    return expanded

def discover_candidates(
    db: Session,
    disaster: Disaster,
    platform: str = "facebook",
    provider: DuckDuckGoPublicSearch | None = None,
) -> int:
    """Discover missing-person posts, not general disaster news."""
    provider = provider or DuckDuckGoPublicSearch()

    primary_queries = generate_queries(
        disaster,
        platform=platform,
    )

    primary_results = provider.run_queries(
        primary_queries
    )

    if platform == "facebook":
        # First-stage results must be real person-level posts
        # AND explicitly connected to the selected disaster/event.
        qualified_primary = [
            (query, result)
            for query, result in primary_results
            if is_person_specific_candidate(
                result,
                disaster,
                require_event_context=True,
            )
        ]

        # Only a valid missing-person post is allowed to promote
        # its page/group into a source sweep.
        expanded_results = expand_facebook_sources(
            provider,
            disaster,
            qualified_primary,
        )

        # Source-sweep results can omit the event name/location
        # because the source was discovered from a valid event post.
        qualified_expanded = [
            (query, result)
            for query, result in expanded_results
            if is_person_specific_candidate(
                result,
                disaster,
                require_event_context=True,
            )
        ]

        all_results = (
            qualified_primary
            + qualified_expanded
        )

    else:
        all_results = list(primary_results)

    deduped: list[tuple[str, SearchResult]] = []
    seen_urls: set[str] = set()

    for query, result in all_results:
        canonical = canonicalize_url(result.url)

        if not canonical:
            continue

        if canonical in seen_urls:
            continue

        seen_urls.add(canonical)

        deduped.append(
            (
                query,
                SearchResult(
                    url=canonical,
                    title=result.title,
                    snippet=result.snippet,
                ),
            )
        )

    added = 0

    for query, result in deduped:
        if platform == "facebook":
            if not is_facebook_post_url(result.url):
                continue

        elif platform == "x":
            if "x.com" not in result.url:
                continue

        elif platform != "web":
            if f"{platform}.com" not in result.url:
                continue

        exists = db.scalar(
            select(DiscoveryCandidate.id).where(
                DiscoveryCandidate.disaster_id
                == disaster.id,
                DiscoveryCandidate.url
                == result.url,
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
                status=auto_triage_candidate_status(result, disaster, platform),
            )
        )

        added += 1

    return added
