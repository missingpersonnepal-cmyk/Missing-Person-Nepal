from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from ..config import settings


COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

# Reports often use local spellings. Keep the displayed report text unchanged,
# but retry known variants so those areas can still be placed accurately on maps.
PLACE_QUERY_ALIASES = {
    "syafrubesi": "Syabrubesi, Rasuwa, Nepal",
    "syabrubesi": "Syabrubesi, Rasuwa, Nepal",
    "rasuwagadhi": "Rasuwagadhi, Rasuwa, Nepal",
    "ruwakot and majhimtar": "Ruwakot, Majhimtar, Nuwakot, Nepal",
}


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float
    label: str | None = None


def parse_coords(value: str | None) -> GeoPoint | None:
    if not value:
        return None
    match = COORD_RE.match(value)
    if not match:
        return None
    return GeoPoint(lat=float(match.group(1)), lon=float(match.group(2)))


def _headers() -> dict[str, str]:
    if not settings.geo_api_key.strip():
        return {}
    return {"X-Api-Key": settings.geo_api_key.strip()}


def _response_data(payload):
    if not isinstance(payload, dict):
        return payload
    return payload.get("data", payload)


def _geocode_request(query: str, limit: int) -> list[GeoPoint]:
    if not settings.geo_api_key.strip() or not query.strip():
        return []
    url = f"{settings.geo_api_base_url}/api/geo/geocode"
    with httpx.Client(timeout=15.0) as client:
        response = client.get(url, params={"query": query, "limit": max(1, min(limit, 10)), "language": "en"}, headers=_headers())
        response.raise_for_status()
    data = _response_data(response.json())
    items = data if isinstance(data, list) else data.get("results") if isinstance(data, dict) else None
    results: list[GeoPoint] = []
    for item in items or []:
        lat = item.get("lat") or item.get("latitude")
        lon = item.get("lon") or item.get("lng") or item.get("longitude")
        if lat is None or lon is None:
            continue
        results.append(GeoPoint(
            lat=float(lat),
            lon=float(lon),
            label=(
                item.get("display_name")
                or item.get("displayName")
                or item.get("name")
                or item.get("label")
            ),
        ))
    return results


def geocode_results(query: str, limit: int = 5) -> list[GeoPoint]:
    results = _geocode_request(query, limit)
    if results:
        return results
    alias = PLACE_QUERY_ALIASES.get(query.strip().casefold())
    return _geocode_request(alias, limit) if alias else []


def geocode(query: str) -> GeoPoint | None:
    results = geocode_results(query, limit=1)
    return results[0] if results else None


def reverse_geocode(lat: float, lon: float) -> str | None:
    if not settings.geo_api_key.strip():
        return None
    url = f"{settings.geo_api_base_url}/api/geo/reverse"
    with httpx.Client(timeout=15.0) as client:
        response = client.get(url, params={"lat": lat, "lon": lon, "detail": "road", "language": "en"}, headers=_headers())
        response.raise_for_status()
        data = _response_data(response.json())
    if isinstance(data, dict):
        return (
            data.get("display_name")
            or data.get("displayName")
            or data.get("name")
            or data.get("label")
        )
    return None


def route(origin: str, destination: str, mode: str = "driving") -> dict:
    if not settings.geo_api_key.strip():
        raise RuntimeError("Geo API key is not configured")
    url = f"{settings.geo_api_base_url}/api/geo/route"
    with httpx.Client(timeout=20.0) as client:
        response = client.get(
            url,
            params={"origin": origin, "destination": destination, "mode": mode},
            headers=_headers(),
        )
        response.raise_for_status()
        data = _response_data(response.json())
        return data if isinstance(data, dict) else {"data": data}
