from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_", "fbclid", "gclid")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"[^\w\s\u0900-\u097f]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if digits.startswith("00977"):
        digits = digits[5:]
    elif digits.startswith("977") and len(digits) > 10:
        digits = digits[3:]
    return digits[-10:] if len(digits) >= 10 else digits


def canonicalize_url(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    parts = urlsplit(value)
    if not parts.scheme:
        parts = urlsplit("https://" + value)
    if parts.scheme.casefold() not in {"http", "https"}:
        return ""
    host = parts.netloc.casefold().removeprefix("www.")
    if not host:
        return ""
    query = []
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        if key.casefold().startswith(TRACKING_PREFIXES):
            continue
        query.append((key, val))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold() or "https", host, path, urlencode(query), ""))


def location_terms(raw: str) -> list[str]:
    return [x.strip() for x in re.split(r"[\n,;]+", raw or "") if x.strip()]


def affected_location_match(location: str | None, affected_locations: str | None) -> bool:
    location_n = normalize_text(location)
    if not location_n:
        return False
    for term in location_terms(affected_locations or ""):
        term_n = normalize_text(term)
        if term_n and (term_n in location_n or location_n in term_n):
            return True
    return False


def detect_platform(url: str | None) -> str:
    """Best-effort platform label from a canonical/public source URL."""
    canonical = canonicalize_url(url)
    if not canonical:
        return "website"
    host = urlsplit(canonical).netloc.casefold()
    if host.endswith("facebook.com") or host.endswith("fb.com"):
        return "facebook"
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith("tiktok.com"):
        return "tiktok"
    if host.endswith("x.com") or host.endswith("twitter.com"):
        return "x"
    if host.endswith("reddit.com"):
        return "reddit"
    return "website"
