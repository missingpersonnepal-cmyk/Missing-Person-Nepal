from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from ..config import settings


COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


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


def geocode(query: str) -> GeoPoint | None:
    if not settings.geo_api_key.strip() or not query.strip():
        return None
    url = f"{settings.geo_api_base_url}/api/geo/geocode"
    with httpx.Client(timeout=15.0) as client:
        response = client.get(url, params={"query": query, "limit": 1, "language": "en"}, headers=_headers())
        response.raise_for_status()
        data = response.json()
    items = data if isinstance(data, list) else data.get("results") if isinstance(data, dict) else None
    if not items:
        return None
    first = items[0]
    lat = first.get("lat") or first.get("latitude")
    lon = first.get("lon") or first.get("lng") or first.get("longitude")
    if lat is None or lon is None:
        return None
    label = first.get("display_name") or first.get("name") or first.get("label")
    return GeoPoint(lat=float(lat), lon=float(lon), label=label)


def reverse_geocode(lat: float, lon: float) -> str | None:
    if not settings.geo_api_key.strip():
        return None
    url = f"{settings.geo_api_base_url}/api/geo/reverse"
    with httpx.Client(timeout=15.0) as client:
        response = client.get(url, params={"lat": lat, "lon": lon, "detail": "road", "language": "en"}, headers=_headers())
        response.raise_for_status()
        data = response.json()
    if isinstance(data, dict):
        return data.get("display_name") or data.get("name") or data.get("label")
    return None

