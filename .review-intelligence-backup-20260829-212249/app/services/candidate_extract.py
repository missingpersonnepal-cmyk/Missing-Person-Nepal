from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ..models import Disaster, DiscoveryCandidate


NEPALI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?977[-\s]?)?(9\d(?:[\s-]?\d){8})(?!\d)"
)

AGE_PATTERNS = [
    re.compile(r"\bage\s*[:\-]?\s*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})\s*years?\s*old\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})\s*(?:yrs?|y/o)\b", re.IGNORECASE),
    re.compile(r"\bउमेर\s*[:\-]?\s*(\d{1,3})\b"),
    re.compile(r"\((\d{1,3})\)"),
]

NAME_PATTERNS = [
    re.compile(
        r"\bPerson\s+Missing\s+"
        r"(?:Mr\.?|Ms\.?|Mrs\.?|Er\.?)?\s*"
        r"([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bMissing\s+Person\s*[:\-]?\s*"
        r"(?:Mr\.?|Ms\.?|Mrs\.?|Er\.?)?\s*"
        r"([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bName\s*[:\-]\s*"
        r"([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,4})",
        re.IGNORECASE,
    ),
]

NEPALI_NAME_RE = re.compile(
    r"(?:नाम|नाम थर)\s*[:\-]?\s*([\u0900-\u097F][\u0900-\u097F\s.'’-]{1,100})"
)

STOP_WORDS = {
    "was", "is", "has", "who", "from", "working", "works", "last",
    "missing", "person", "people", "out", "contact", "facebook",
}

DETAIL_KEYWORDS = (
    "address", "resident", "residence", "home", "work", "works", "working",
    "workplace", "occupation", "profession", "employee", "engineer", "driver",
    "guide", "bank", "hydropower", "hotel", "guest house", "family", "father",
    "mother", "son", "daughter", "brother", "sister", "husband", "wife",
    "travel", "travelling", "traveling", "route", "vehicle", "bike", "car",
    "ठेगाना", "बसोबास", "पेशा", "कार्यरत", "काम", "परिवार", "बुबा", "आमा",
    "छोरा", "छोरी", "दाजु", "भाइ", "दिदी", "बहिनी", "यात्रा", "सवारी",
)


def _normalize_digits(text: str) -> str:
    return text.translate(NEPALI_DIGITS)


def _clean_name(value: str) -> str:
    words = value.strip(" ,-–—.").split()
    cleaned: list[str] = []

    for word in words:
        if word.casefold().rstrip(".,") in STOP_WORDS:
            break
        cleaned.append(word.strip(" ,-–—."))

    while cleaned and cleaned[0].casefold().rstrip(".") in {"mr", "mrs", "ms", "er"}:
        cleaned.pop(0)

    return " ".join(cleaned).strip()


def _extract_name(title: str, snippet: str, ocr_text: str = "") -> str | None:
    # Title is intentionally searched first because search-engine snippets can
    # sometimes contain text stitched from another post.
    for source in (title, snippet, ocr_text):
        if not source:
            continue
        for pattern in NAME_PATTERNS:
            match = pattern.search(source)
            if match:
                value = _clean_name(match.group(1))
                if 2 <= len(value.split()) <= 5:
                    return value

    for nepali_term in ("सम्पर्कविहीन", "सम्पर्क विहीन", "बेपत्ता", "हराएको"):
        if nepali_term not in title:
            continue
        before = title.split(nepali_term, 1)[0]
        if " - " in before:
            before = before.split(" - ")[-1]
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


def _extract_nepali_name(text: str) -> str | None:
    match = NEPALI_NAME_RE.search(text)
    if not match:
        return None
    value = re.split(r"[\n|,;]", match.group(1), maxsplit=1)[0].strip(" .,:;-–—")
    words = value.split()
    if 1 <= len(words) <= 6:
        return value[:255]
    return None


def _extract_age(text: str) -> int | None:
    text = _normalize_digits(text)
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


def _extract_phones(text: str) -> str | None:
    text = _normalize_digits(text)
    found: list[str] = []
    for match in PHONE_RE.finditer(text):
        number = re.sub(r"\D", "", match.group(1))
        if len(number) == 10 and number not in found:
            found.append(number)
        if len(found) >= 3:
            break
    return ", ".join(found) if found else None


def _clean_location(value: str) -> str | None:
    value = re.sub(
        r"^\s*(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:in|at)?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.split(
        r"\b(?:and|who|has|was|is|since|after|before|please|contact)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = value.strip(" ,.;:-–—")
    return value[:250] if value else None


def _extract_location(text: str, disaster: Disaster) -> str | None:
    explicit_patterns = [
        re.compile(r"\blast\s+known\s+location\s*[:\-]?\s*([^.;\n]+)", re.IGNORECASE),
        re.compile(r"\blast\s+known\s+to\s+be\s+in\s+([^.;\n]+)", re.IGNORECASE),
        re.compile(r"\blast\s+seen(?:\s+location)?\s*[:\-]\s*([^.;\n]+)", re.IGNORECASE),
        re.compile(r"\blast\s+seen\s+(?:at|in)\s+([^.;\n]+)", re.IGNORECASE),
        re.compile(r"\bmissing\s+from\s+([^.;\n]+)", re.IGNORECASE),
        re.compile(r"\blocation\s*[:\-]\s*([^.;\n]+)", re.IGNORECASE),
        re.compile(r"(?:अन्तिम\s+पटक\s+देखिएको\s+स्थान|हराएको\s+स्थान|स्थान)\s*[:\-]?\s*([^.;\n]+)"),
    ]

    for pattern in explicit_patterns:
        match = pattern.search(text)
        if match:
            value = _clean_location(match.group(1))
            if value and not re.fullmatch(r"\d{1,2}(?::\d{2})?\s*(?:am|pm)?", value, re.IGNORECASE):
                return value

    folded = text.casefold()
    matches = [
        location
        for location in disaster.locations()
        if location.casefold() in folded
    ]
    if matches:
        generic_tokens = {token.casefold() for token in disaster.name.split()}
        specific = [
            location
            for location in matches
            if location.casefold() not in generic_tokens
        ]
        if specific:
            matches = specific
        return sorted(matches, key=len, reverse=True)[0]

    workplace = re.search(r"\bworks?\s+at\s+([^.;\n]+)", text, re.IGNORECASE)
    if workplace:
        return _clean_location(workplace.group(1))

    return None


def _extract_gender(text: str) -> str | None:
    match = re.search(r"\bgender\s*[:\-]\s*(male|female)\b", text, re.IGNORECASE)
    if match:
        return "Male" if match.group(1).casefold() == "male" else "Female"

    match = re.search(r"(?:लिङ्ग|लिंग)\s*[:\-]?\s*(पुरुष|महिला)\b", text)
    if match:
        return "Male" if match.group(1) == "पुरुष" else "Female"

    return None


def _extract_time(text: str) -> str | None:
    text = _normalize_digits(text)
    patterns = [
        re.compile(
            r"(?:last\s+(?:seen|contacted)|time)\D{0,25}"
            r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:last\s+(?:seen|contacted)|time)\D{0,25}"
            r"([01]?\d|2[0-3]):([0-5]\d)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(\d{1,2}):(\d{2})\s*(am|pm)\b", re.IGNORECASE),
    ]

    for pattern in patterns:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groups()
        try:
            hour = int(groups[0])
            minute = int(groups[1] or 0)
        except (TypeError, ValueError):
            continue
        ampm = groups[2].casefold() if len(groups) >= 3 and groups[2] else None
        if ampm:
            if not 1 <= hour <= 12 or not 0 <= minute <= 59:
                continue
            if ampm == "pm" and hour != 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
        elif not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        return f"{hour:02d}:{minute:02d}"

    return None


def _extract_date(text: str) -> str | None:
    text = _normalize_digits(text)
    patterns = [
        (re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b"), "%Y-%m-%d"),
        (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b"), "%d-%m-%Y"),
    ]

    for pattern, kind in patterns:
        match = pattern.search(text)
        if not match:
            continue
        try:
            if kind == "%Y-%m-%d":
                value = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            else:
                value = datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            continue
        return value.date().isoformat()

    month_match = re.search(
        r"\b(?:last\s+(?:seen|contacted)\s*(?:on|since)?\s*)?"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if month_match:
        try:
            value = datetime.strptime(
                f"{month_match.group(1)} {month_match.group(2)} {month_match.group(3)}",
                "%B %d %Y",
            )
            return value.date().isoformat()
        except ValueError:
            pass

    return None


def _extract_clothing(text: str) -> str | None:
    patterns = [
        re.compile(r"\b(?:last\s+seen\s+)?wearing\s+([^.;\n]+)", re.IGNORECASE),
        re.compile(r"\bclothing\s*[:\-]\s*([^.;\n]+)", re.IGNORECASE),
        re.compile(r"(?:लगाएको\s+लुगा|पोशाक|लुगा)\s*[:\-]?\s*([^.;\n]+)"),
    ]
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip(" ,.;:-–—")
            if value:
                return value[:1000]
    return None


def _build_identification_details(snippet: str, ocr_text: str, combined: str) -> str | None:
    details: list[str] = []

    def has_detail_keyword(piece: str) -> bool:
        for keyword in DETAIL_KEYWORDS:
            if keyword.isascii():
                if re.search(r"\b" + re.escape(keyword) + r"\b", piece, re.IGNORECASE):
                    return True
            elif keyword in piece:
                return True
        return False

    def add(label: str, value: str) -> None:
        value = " ".join(value.split()).strip()
        if not value:
            return
        entry = f"{label}: {value}"
        if entry not in details:
            details.append(entry)

    if snippet.strip():
        add("Source snippet", snippet[:1800])

    for piece in re.split(r"[\n\r]+|(?<=[.!?])\s+", combined):
        if has_detail_keyword(piece):
            add("Other source detail", piece[:700])
        if len(details) >= 8:
            break

    if ocr_text.strip():
        add("OCR text", ocr_text[:3000])

    return "\n".join(details) or None


def extract_candidate_prefill(
    candidate: DiscoveryCandidate,
    disaster: Disaster,
    ocr_text: str = "",
) -> dict[str, Any]:
    """Extract only information explicitly present in public text/OCR.

    OCR reads written text from an image. Nothing is inferred from a person's
    face, appearance, or name.
    """
    title = candidate.title or ""
    snippet = candidate.snippet or ""
    combined = "\n".join(part for part in (title, snippet, ocr_text) if part).strip()
    normalized = _normalize_digits(combined)

    name_ne = _extract_nepali_name(normalized)
    name = _extract_name(title, snippet, ocr_text)
    if name is None and name_ne:
        # The master record requires a name. A written Nepali name is valid
        # source text, so use it rather than inventing a transliteration.
        name = name_ne

    return {
        "name": name,
        "name_ne": name_ne,
        "age": _extract_age(normalized),
        "gender": _extract_gender(normalized),
        "last_seen_date": _extract_date(normalized),
        "last_seen_time": _extract_time(normalized),
        "last_seen_location": _extract_location(normalized, disaster),
        "clothing": _extract_clothing(normalized),
        "identification_details": _build_identification_details(
            snippet,
            ocr_text,
            normalized,
        ),
        "public_contact_number": _extract_phones(normalized),
    }
