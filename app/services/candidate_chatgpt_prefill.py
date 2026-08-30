from __future__ import annotations

import ast
import json
import re
from typing import Any

from ..models import Disaster, DiscoveryCandidate


PREFILL_FIELDS = (
    "name",
    "name_ne",
    "age",
    "gender",
    "last_seen_date",
    "last_seen_time",
    "last_seen_location",
    "clothing",
    "identification_details",
    "public_contact_number",
)


class ChatGPTPrefillParseError(ValueError):
    pass


def build_candidate_chatgpt_prefill_prompt(
    disaster: Disaster,
    candidate: DiscoveryCandidate,
    *,
    source_post_text: str = "",
    ocr_text: str = "",
) -> str:
    """Build a zero-API-cost ChatGPT prefill prompt for one reviewed source."""
    locations = disaster.locations()
    evidence = {
        "event": {
            "name": disaster.name,
            "type": disaster.disaster_type,
            "start_date": disaster.start_date.isoformat(),
            "affected_locations": locations,
        },
        "source": {
            "platform": candidate.platform,
            "url": candidate.url,
            "title": candidate.title or "",
            "indexed_snippet": candidate.snippet or "",
            "public_post_text": source_post_text or "",
            "ocr_text_from_source_image": ocr_text or "",
        },
    }

    payload = json.dumps(evidence, ensure_ascii=False, indent=2)

    return f"""You are preparing a prefill for an administrator of a Nepal disaster missing-person registry.

The administrator has already marked this public source as RELEVANT. Extract every explicitly reported missing person from the supplied textual evidence.

STRICT SAFETY AND EVIDENCE RULES
- Use only the supplied title, indexed snippet, public post text, and OCR text.
- Never identify a person from a photograph or face.
- Never infer gender, age, identity, ethnicity, relationship, clothing, location, phone number, or any other attribute from appearance.
- Do not invent, guess, translate a name unless the source explicitly provides that form, or merge details belonging to different people.
- If a field cannot be tied to a specific named person, return null for that field.
- Gender must be "Male", "Female", or null, and only when explicitly stated in textual evidence.
- Keep dates as YYYY-MM-DD only when the evidence supports an exact Gregorian date.
- Keep times as HH:MM only when explicitly stated.
- Preserve useful location wording, workplace/address clues, family relationship details, identifying textual details, and public contact details.
- A single post can report MULTIPLE missing people. Return every explicitly named missing person as a separate object.
- Do not create a separate person merely because a relative/contact name appears.
- Public phone/contact numbers may be returned only when present in supplied public evidence.

RETURN FORMAT
Return one VALID JSON object only. Do not use markdown fences, comments, trailing commas, single quotes, or explanatory text outside the JSON. Before answering, verify that the JSON parses successfully.

{{
  "people": [
    {{
      "name": "string or null",
      "name_ne": "string or null",
      "age": null,
      "gender": "Male or Female or null",
      "last_seen_date": "YYYY-MM-DD or null",
      "last_seen_time": "HH:MM or null",
      "last_seen_location": "string or null",
      "clothing": "string or null",
      "identification_details": "string or null",
      "public_contact_number": "string or null"
    }}
  ],
  "source_notes": "short note about ambiguity, multiple people, or evidence limitations; null if unnecessary"
}}

SOURCE EVIDENCE
{payload}
"""


def _extract_json_region(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise ChatGPTPrefillParseError("No ChatGPT result was pasted.")

    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.I | re.S)
    if fence:
        text = fence.group(1).strip()

    starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
    if not starts:
        return text
    start = min(starts)

    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return text[start:]


def _remove_trailing_commas(text: str) -> str:
    output: list[str] = []
    in_string = False
    escape = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == ",":
            look = index + 1
            while look < len(text) and text[look].isspace():
                look += 1
            if look < len(text) and text[look] in "}]":
                index += 1
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _insert_missing_property_commas(text: str) -> str:
    # Conservative repair for a common ChatGPT formatting slip such as
    # {"name":"A Person" "age":32}. It only inserts a comma when a
    # complete JSON value is followed by whitespace and another quoted key.
    key = r'"(?:\\.|[^"\\])*"\s*:'
    value = r'(?:"(?:\\.|[^"\\])*"|true|false|null|-?\d+(?:\.\d+)?)'
    repaired = re.sub(
        rf'({value})\s+(?=({key}))',
        r'\1, ',
        text,
        flags=re.IGNORECASE,
    )
    repaired = re.sub(
        rf'([}}\]])\s+(?=({key}))',
        r'\1, ',
        repaired,
    )
    return repaired


def _load_relaxed_json(raw: str) -> Any:
    region = _extract_json_region(raw)
    no_trailing = _remove_trailing_commas(region)
    attempts = [
        region,
        no_trailing,
        _insert_missing_property_commas(no_trailing),
    ]
    last_error: Exception | None = None

    for candidate in attempts:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc

    # ChatGPT occasionally emits a Python-style dict with single quotes.
    try:
        value = ast.literal_eval(region)
        if isinstance(value, (dict, list)):
            return value
    except (ValueError, SyntaxError) as exc:
        last_error = exc

    if isinstance(last_error, json.JSONDecodeError):
        start = max(0, last_error.pos - 45)
        end = min(len(region), last_error.pos + 45)
        excerpt = region[start:end].replace("\n", " ")
        raise ChatGPTPrefillParseError(
            f"Invalid JSON near line {last_error.lineno}, column {last_error.colno}. "
            f"Check this area: {excerpt!r}"
        ) from last_error

    raise ChatGPTPrefillParseError(
        "The pasted result is not valid JSON. Copy the full ChatGPT JSON response and try again."
    ) from last_error


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"null", "none", "unknown"}:
        return None
    return text


def _clean_age(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        age = int(value)
    except (TypeError, ValueError):
        return None
    return age if 0 < age < 120 else None


def _clean_gender(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    folded = text.casefold()
    if folded == "male":
        return "Male"
    if folded == "female":
        return "Female"
    return None


def _normalize_person(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _clean_text(raw.get("name")),
        "name_ne": _clean_text(raw.get("name_ne")),
        "age": _clean_age(raw.get("age")),
        "gender": _clean_gender(raw.get("gender")),
        "last_seen_date": _clean_text(raw.get("last_seen_date")),
        "last_seen_time": _clean_text(raw.get("last_seen_time")),
        "last_seen_location": _clean_text(raw.get("last_seen_location")),
        "clothing": _clean_text(raw.get("clothing")),
        "identification_details": _clean_text(raw.get("identification_details")),
        "public_contact_number": _clean_text(raw.get("public_contact_number")),
    }


def parse_candidate_chatgpt_prefill(raw: str) -> dict[str, Any]:
    payload = _load_relaxed_json(raw)

    if isinstance(payload, list):
        payload = {"people": payload}
    elif isinstance(payload, dict) and "people" not in payload and "name" in payload:
        payload = {"people": [payload]}

    if not isinstance(payload, dict):
        raise ChatGPTPrefillParseError("ChatGPT result must be a JSON object.")

    raw_people = payload.get("people")
    if not isinstance(raw_people, list) or not raw_people:
        raise ChatGPTPrefillParseError(
            'ChatGPT result must contain a non-empty "people" array.'
        )

    people = [
        _normalize_person(item)
        for item in raw_people
        if isinstance(item, dict)
    ]
    people = [item for item in people if any(item.values())]
    if not people:
        raise ChatGPTPrefillParseError("No usable person objects were found.")

    return {
        "people": people,
        "source_notes": _clean_text(payload.get("source_notes")),
    }
