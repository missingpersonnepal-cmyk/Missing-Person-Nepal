from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from .discovery import SearchResult
from .normalization import canonicalize_url


@dataclass(slots=True)
class SearchProviderStatus:
    name: str
    available: bool
    detail: str


class SearchProviderUnavailable(RuntimeError):
    pass


class BravePublicSearch:
    """Official Brave Search API provider.

    Requires BRAVE_SEARCH_API_KEY.
    No Facebook login or private-content access is performed.
    """

    endpoint = (
        "https://api.search.brave.com/res/v1/web/search"
    )

    def __init__(self) -> None:
        self.api_key = (
            os.getenv("BRAVE_SEARCH_API_KEY", "")
            .strip()
        )

        if not self.api_key:
            raise SearchProviderUnavailable(
                "BRAVE_SEARCH_API_KEY is not configured"
            )

        self.client = httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
                "User-Agent": "MissingPersonHub/0.1",
            },
        )

    def search(
        self,
        query: str,
        max_results: int = 15,
    ) -> list[SearchResult]:

        count = min(
            max(max_results, 1),
            20,
        )

        response = self.client.get(
            self.endpoint,
            params={
                "q": query,
                "count": count,
                "search_lang": "en",
                "safesearch": "moderate",
            },
        )

        if response.status_code == 401:
            raise SearchProviderUnavailable(
                "Brave Search API key was rejected"
            )

        if response.status_code == 429:
            raise SearchProviderUnavailable(
                "Brave Search API rate/quota limit reached"
            )

        response.raise_for_status()

        payload = response.json()

        web = payload.get("web") or {}
        rows = web.get("results") or []

        results: list[SearchResult] = []

        for item in rows:
            url = canonicalize_url(
                str(
                    item.get("url")
                    or ""
                )
            )

            if not url:
                continue

            results.append(
                SearchResult(
                    url=url,
                    title=str(
                        item.get("title")
                        or ""
                    ),
                    snippet=str(
                        item.get("description")
                        or ""
                    ),
                )
            )

        return results


def brave_status() -> SearchProviderStatus:
    key = (
        os.getenv(
            "BRAVE_SEARCH_API_KEY",
            "",
        )
        .strip()
    )

    if not key:
        return SearchProviderStatus(
            name="Brave Search API",
            available=False,
            detail="API key not configured",
        )

    return SearchProviderStatus(
        name="Brave Search API",
        available=True,
        detail="Configured",
    )


class TavilyPublicSearch:
    """Official Tavily Search API provider.

    Uses only publicly indexed web content.
    Facebook login or private-content access is never attempted.
    """

    endpoint = "https://api.tavily.com/search"

    def __init__(self) -> None:
        self.api_key = (
            os.getenv("TAVILY_API_KEY", "")
            .strip()
        )

        if not self.api_key:
            raise SearchProviderUnavailable(
                "TAVILY_API_KEY is not configured"
            )

        self.client = httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers={
                "Authorization": (
                    f"Bearer {self.api_key}"
                ),
                "Content-Type": "application/json",
                "User-Agent": "MissingPersonHub/0.1",
            },
        )

    def search(
        self,
        query: str,
        max_results: int = 20,
        *,
        include_domains: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[SearchResult]:

        limit = min(
            max(int(max_results), 1),
            20,
        )

        payload: dict[str, object] = {
            "query": query,
            "search_depth": "basic",
            "max_results": limit,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }

        if include_domains:
            payload["include_domains"] = include_domains

        if start_date:
            payload["start_date"] = start_date

        if end_date:
            payload["end_date"] = end_date

        response = self.client.post(
            self.endpoint,
            json=payload,
        )

        if response.status_code == 401:
            raise SearchProviderUnavailable(
                "Tavily API key was rejected"
            )

        if response.status_code in {
            429,
            432,
            433,
        }:
            raise SearchProviderUnavailable(
                "Tavily quota or rate limit reached"
            )

        response.raise_for_status()

        data = response.json()

        results: list[SearchResult] = []

        for item in data.get("results") or []:

            url = canonicalize_url(
                str(
                    item.get("url")
                    or ""
                )
            )

            if not url:
                continue

            results.append(
                SearchResult(
                    url=url,
                    title=str(
                        item.get("title")
                        or ""
                    ),
                    snippet=str(
                        item.get("content")
                        or ""
                    ),
                )
            )

        return results


def tavily_status() -> SearchProviderStatus:

    key = (
        os.getenv(
            "TAVILY_API_KEY",
            "",
        )
        .strip()
    )

    if not key:
        return SearchProviderStatus(
            name="Tavily Search API",
            available=False,
            detail="API key not configured",
        )

    return SearchProviderStatus(
        name="Tavily Search API",
        available=True,
        detail="Configured",
    )



class SerperPublicSearch:
    """Google search through the Serper API.

    Discovery only. Results are public search-index signals and are not
    treated as verified missing-person facts.

    The deliberately small request payload mirrors the request that was
    verified successfully during the live Facebook coverage test.
    """

    endpoint = "https://google.serper.dev/search"

    def __init__(self) -> None:
        self.api_key = os.getenv("SERPER_API_KEY", "").strip()

        if not self.api_key:
            raise SearchProviderUnavailable(
                "SERPER_API_KEY is not configured"
            )

        self.client = httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
                "User-Agent": "MissingPersonHub/0.1",
            },
        )

    def search(
        self,
        query: str,
        max_results: int = 10,
        **kwargs,
    ) -> list[SearchResult]:

        query = (query or "").strip()

        if not query:
            return []

        # The live validation used Serper's default result window
        # successfully. Keep the API request minimal for V0 instead
        # of sending optional parameters that previously produced 400s.
        payload = {
            "q": query,
        }

        response = self.client.post(
            self.endpoint,
            json=payload,
        )

        if response.status_code == 401:
            raise SearchProviderUnavailable(
                "Serper API key was rejected"
            )

        if response.status_code == 429:
            raise SearchProviderUnavailable(
                "Serper quota or rate limit reached"
            )

        if response.status_code == 400:
            detail = (response.text or "").strip()

            if len(detail) > 300:
                detail = detail[:300]

            raise SearchProviderUnavailable(
                "Serper rejected the search request"
                + (f": {detail}" if detail else "")
            )

        response.raise_for_status()

        data = response.json()

        organic = data.get("organic") or []

        # Serper's validated default currently yields around ten results.
        # Respect the caller's requested ceiling without increasing the
        # provider-side API request size yet.
        try:
            limit = max(1, min(int(max_results), 10))
        except (TypeError, ValueError):
            limit = 10

        results: list[SearchResult] = []
        seen: set[str] = set()

        for item in organic:

            raw_url = str(
                item.get("link")
                or item.get("url")
                or ""
            ).strip()

            if not raw_url:
                continue

            url = canonicalize_url(raw_url)

            if not url or url in seen:
                continue

            seen.add(url)

            results.append(
                SearchResult(
                    url=url,
                    title=str(
                        item.get("title")
                        or ""
                    ).strip(),
                    snippet=str(
                        item.get("snippet")
                        or ""
                    ).strip(),
                )
            )

            if len(results) >= limit:
                break

        return results


def serper_status() -> SearchProviderStatus:
    key = os.getenv("SERPER_API_KEY", "").strip()

    if not key:
        return SearchProviderStatus(
            name="Serper / Google Search",
            available=False,
            detail="API key not configured",
        )

    return SearchProviderStatus(
        name="Serper / Google Search",
        available=True,
        detail="Configured",
    )
