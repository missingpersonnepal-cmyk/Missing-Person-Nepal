from __future__ import annotations

import re
from typing import Any

from ..models import Disaster, DiscoveryCandidate


PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?977[-\s]?)?(9\d{9})(?!\d)"
)

AGE_PATTERNS = [
    re.compile(
        r"\bage\s*[:\-]?\s*(\d{1,2})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\((\d{1,2})\)",
    ),
    re.compile(
        r"\b(\d{1,2})\s*years?\s*old\b",
        re.IGNORECASE,
    ),
]

NAME_PATTERNS = [
    re.compile(
        r"\bPerson\s+Missing\s+"
        r"(?:Mr\.?|Ms\.?|Mrs\.?|Er\.?)?\s*"
        r"([A-Z][A-Za-z'.-]+"
        r"(?:\s+[A-Z][A-Za-z'.-]+){1,4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bMissing\s+Person\s*[:\-]?\s*"
        r"(?:Mr\.?|Ms\.?|Mrs\.?|Er\.?)?\s*"
        r"([A-Z][A-Za-z'.-]+"
        r"(?:\s+[A-Z][A-Za-z'.-]+){1,4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bName\s*[:\-]\s*"
        r"([A-Z][A-Za-z'.-]+"
        r"(?:\s+[A-Z][A-Za-z'.-]+){1,4})",
        re.IGNORECASE,
    ),
]

STOP_WORDS = {
    "was",
    "is",
    "has",
    "who",
    "from",
    "working",
    "works",
    "last",
    "missing",
    "person",
    "people",
    "out",
    "contact",
    "facebook",
}


def _clean_name(value: str) -> str:
    words = value.strip(" ,-–—.").split()
    cleaned: list[str] = []

    for word in words:
        if (
            word.casefold().rstrip(".,")
            in STOP_WORDS
        ):
            break

        cleaned.append(
            word.strip(" ,-–—.")
        )

    while (
        cleaned
        and cleaned[0].casefold().rstrip(".")
        in {"mr", "mrs", "ms", "er"}
    ):
        cleaned.pop(0)

    return " ".join(cleaned).strip()


def _extract_name(
    title: str,
    snippet: str,
) -> str | None:

    combined = f"{title} {snippet}"

    for pattern in NAME_PATTERNS:
        match = pattern.search(combined)

        if match:
            value = _clean_name(
                match.group(1)
            )

            if len(value.split()) >= 2:
                return value

    for nepali_term in (
        "सम्पर्कविहीन",
        "सम्पर्क विहीन",
        "बेपत्ता",
        "हराएको",
    ):
        if nepali_term not in title:
            continue

        before = title.split(
            nepali_term,
            1,
        )[0]

        if " - " in before:
            before = before.split(
                " - "
            )[-1]

        before = re.sub(
            r"^(?:Mr|Mrs|Ms|Er)\.?\s+",
            "",
            before.strip(),
            flags=re.IGNORECASE,
        )

        value = _clean_name(before)

        if 2 <= len(value.split()) <= 5:
            return value

    return None


def _extract_age(
    text: str,
) -> int | None:

    for pattern in AGE_PATTERNS:
        match = pattern.search(text)

        if not match:
            continue

        try:
            age = int(match.group(1))
        except ValueError:
            continue

        if 0 < age < 120:
            return age

    return None


def _extract_phone(
    text: str,
) -> str | None:

    match = PHONE_RE.search(text)

    if not match:
        return None

    return match.group(1)


def _extract_location(
    text: str,
    disaster: Disaster,
) -> str | None:

    folded = text.casefold()

    matches = [
        location
        for location in disaster.locations()
        if location.casefold() in folded
    ]

    if matches:
        # Prefer specific affected places such as Timure or
        # Betrawati over the district-level word Rasuwa.
        generic_tokens = {
            token.casefold()
            for token in disaster.name.split()
        }

        specific = [
            location
            for location in matches
            if location.casefold()
            not in generic_tokens
        ]

        if specific:
            matches = specific

        return sorted(
            matches,
            key=len,
            reverse=True,
        )[0]

    patterns = [
        re.compile(
            r"\blast known to be in\s+([^.;]+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\blast seen(?: at| in)?\s+([^.;]+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bmissing from\s+([^.;]+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bworks? at\s+([^.;]+)",
            re.IGNORECASE,
        ),
    ]

    for pattern in patterns:
        match = pattern.search(text)

        if not match:
            continue

        value = match.group(1).strip()

        value = re.split(
            r"\b(?:and|has|was|is)\b",
            value,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        value = value.strip(" ,.-")

        if value:
            return value[:250]

    return None


def _extract_gender(
    text: str,
) -> str | None:

    match = re.search(
        r"\bgender\s*[:\-]\s*"
        r"(male|female|other)\b",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    return match.group(1).casefold()


def extract_candidate_prefill(
    candidate: DiscoveryCandidate,
    disaster: Disaster,
) -> dict[str, Any]:
    """Extract public text only.

    Nothing is inferred from a person's appearance.
    """
    title = candidate.title or ""
    snippet = candidate.snippet or ""

    text = f"{title} {snippet}".strip()

    return {
        "name": _extract_name(
            title,
            snippet,
        ),
        "name_ne": None,
        "age": _extract_age(text),
        "gender": _extract_gender(text),
        "last_seen_date": None,
        "last_seen_time": None,
        "last_seen_location": (
            _extract_location(
                text,
                disaster,
            )
        ),
        "clothing": None,
        "identification_details": (
            snippet.strip()
            or None
        ),
        "public_contact_number": (
            _extract_phone(text)
        ),
    }
