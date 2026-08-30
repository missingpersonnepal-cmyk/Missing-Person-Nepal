from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import httpx

from ..models import Disaster, DiscoveryCandidate
from .candidate_chatgpt_prefill import parse_candidate_chatgpt_prefill
from .source_images import is_allowed_public_image_url


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_TIMEOUT_SECONDS = 45.0


class OpenAIPrefillError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAIPrefillStatus:
    available: bool
    model: str
    detail: str


def openai_prefill_status() -> OpenAIPrefillStatus:
    key = str(os.getenv("OPENAI_API_KEY") or "").strip()
    model = str(os.getenv("OPENAI_PREFILL_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if key:
        return OpenAIPrefillStatus(
            available=True,
            model=model,
            detail="Backend AI prefill is configured. One API request extracts every explicitly named missing person from the reviewed public source.",
        )
    return OpenAIPrefillStatus(
        available=False,
        model=model,
        detail="Set OPENAI_API_KEY on the server to enable one-click backend AI prefill. The manual copy/paste fallback remains available.",
    )


def _schema() -> dict[str, Any]:
    nullable_string: dict[str, Any] = {"type": ["string", "null"]}
    person_properties = {
        "name": nullable_string,
        "name_ne": nullable_string,
        "age": {"type": ["integer", "null"]},
        "gender": {
            "type": ["string", "null"],
            "enum": ["Male", "Female", None],
        },
        "last_seen_date": nullable_string,
        "last_seen_time": nullable_string,
        "last_seen_location": nullable_string,
        "clothing": nullable_string,
        "identification_details": nullable_string,
        "public_contact_number": nullable_string,
        # These two fields are not written to the person record.  They are an
        # admission proof used by the backend to stop author/contact/relative
        # names from becoming separate missing-person records.
        "evidence_source": {
            "type": "string",
            "enum": [
                "title",
                "indexed_snippet",
                "public_post_text",
                "ocr_text",
                "source_image_text",
            ],
        },
        "missing_status_evidence": {"type": "string"},
    }
    return {
        "type": "object",
        "properties": {
            "people": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": person_properties,
                    "required": list(person_properties),
                    "additionalProperties": False,
                },
            },
            "source_notes": nullable_string,
        },
        "required": ["people", "source_notes"],
        "additionalProperties": False,
    }


def _instructions() -> str:
    return """You extract missing-person registry fields from a public source that a human administrator has already marked relevant.

Use ONLY the supplied source title, indexed snippet, public post text, OCR text, and visible WRITTEN TEXT in any supplied source image.

CRITICAL PERSON-ADMISSION RULE
A name belongs in people ONLY when the supplied evidence explicitly reports THAT SPECIFIC PERSON as missing, out of contact, unaccounted for, lost, or as an entry in a clearly labeled missing-person list.

Before returning, internally classify every name you see. Exclude names that are merely:
- the Facebook/page/profile/post author, uploader, influencer, group/page name, or source account;
- a relative, spouse, parent, sibling, friend, colleague, reporter, rescuer, witness, contact person, or person to call;
- a tagged/commenting person, image credit, company/project representative, or name from related/recommended/navigation content;
- a found, rescued, injured, deceased, or identified person unless the same evidence also explicitly says that person is currently missing;
- another name that happens to appear near a missing-person report without being described as missing.

If the post says one person is missing and gives another person's name or phone number as the contact, return ONLY the missing person. Do not turn the contact into a second person.

For EVERY returned person you MUST provide:
- evidence_source: exactly one of title, indexed_snippet, public_post_text, ocr_text, source_image_text.
- missing_status_evidence: a short verbatim excerpt, maximum 500 characters, from that source which contains the person's written name (or name_ne) AND the wording/heading that establishes that person as missing/out of contact. Keep the excerpt tightly focused on that person's missing status.

If you cannot produce that direct evidence for a name, DO NOT return that name. This rule is more important than maximizing recall.

Safety and evidence rules:
- Never identify a person from a face or photograph.
- If an image is supplied, use it only to read visible written/printed text. Do not infer identity, gender, age, ethnicity, clothing, location, relationship, or any other attribute from appearance.
- Never invent or guess facts.
- Never translate or alter a person's name unless that exact form is explicitly present in the supplied evidence.
- Keep each person's details separate. Do not merge details between people.
- A contact/relative named only as the person to call is not a missing person unless the evidence explicitly says that person is missing.
- Return every explicitly named missing person in a genuine multi-person post or labeled missing-person list.
- Do not return the same person twice because of spelling/case variants when the source clearly refers to one person.
- Gender must be Male, Female, or null, and only when explicitly stated in textual evidence.
- Dates must be exact Gregorian YYYY-MM-DD values only when explicitly supported. Do not convert Bikram Sambat dates or relative dates.
- Times must be HH:MM only when explicitly stated.
- Public phone/contact numbers may be returned only when present in the supplied public evidence.
- Preserve useful workplace, address, family relationship, identifying, and last-seen wording in identification_details when it belongs to that specific person.
- If no usable named missing person can be established, return an empty people array and explain the evidence limitation in source_notes.

FINAL CHECK BEFORE RETURNING
For each object in people, ask: 'Where does the source explicitly say THIS person is missing?' If the answer is only implication, authorship, contact information, relationship, or proximity to another person's report, remove that object."""


def _evidence_text(
    disaster: Disaster,
    candidate: DiscoveryCandidate,
    *,
    source_post_text: str,
    ocr_text: str,
) -> str:
    evidence = {
        "event": {
            "name": disaster.name,
            "type": disaster.disaster_type,
            "start_date": disaster.start_date.isoformat(),
            "affected_locations": disaster.locations(),
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
    return "SOURCE EVIDENCE\n" + json.dumps(evidence, ensure_ascii=False, indent=2)



_MISSING_STATUS_TERMS = (
    "missing",
    "missing person",
    "missing persons",
    "out of contact",
    "out-of-contact",
    "unaccounted for",
    "contact lost",
    "cannot be contacted",
    "can't be contacted",
    "could not be contacted",
    "no contact",
    "contact chaina",
    "samparka chaina",
    "सम्पर्कविहीन",
    "सम्पर्क विहीन",
    "बेपत्ता",
    "हराएको",
    "हराइरहेको",
    "सम्पर्कमा छैन",
    "सम्पर्क हुन सकेको छैन",
    "सम्पर्क हुन नसकेको",
    "फेला परेको छैन",
    "खोजी भइरहेको",
)


def _match_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = " ".join(text.split()).casefold()
    return text


def _name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def _has_missing_status_language(value: str) -> bool:
    folded = _match_text(value)
    return any(_match_text(term) in folded for term in _MISSING_STATUS_TERMS)



def _has_direct_missing_relation(excerpt: str, names: list[str]) -> bool:
    """Require missing-status language to grammatically/structurally target the name.

    This deliberately distinguishes a heading such as ``PERSON MISSING Rajesh``
    from a preceding author string such as ``Bikki Gurung | PERSON MISSING Rajesh``.
    Simple proximity would incorrectly mark the author as missing.
    """
    text = _match_text(excerpt)
    if not text:
        return False

    heading_terms = (
        "person missing",
        "missing person",
        "missing persons",
        "बेपत्ता",
        "सम्पर्कविहीन",
        "सम्पर्क विहीन",
        "हराएको",
    )
    after_name_patterns = (
        r"(?:is|was|has been|have been|reported|remains|remain|still)\s+missing\b",
        r"\bmissing\b",
        r"out[ -]of[ -]contact",
        r"unaccounted for",
        r"contact (?:has been )?lost",
        r"cannot be contacted",
        r"can't be contacted",
        r"could not be contacted",
        r"no contact",
        r"contact chaina",
        r"samparka chaina",
        r"सम्पर्कविहीन",
        r"सम्पर्क विहीन",
        r"बेपत्ता",
        r"हराएको",
        r"हराइरहेको",
        r"सम्पर्कमा छैन",
        r"सम्पर्क हुन सकेको छैन",
        r"सम्पर्क हुन नसकेको",
        r"फेला परेको छैन",
    )

    for raw_name in names:
        name = _match_text(raw_name)
        if not name:
            continue
        start = 0
        while True:
            pos = text.find(name, start)
            if pos < 0:
                break
            before = text[max(0, pos - 180):pos]
            after = text[pos + len(name):pos + len(name) + 180]

            # A missing-person heading/list label normally precedes the target.
            if any(term in before for term in heading_terms):
                return True

            # Status wording following the name must read as a predicate/status,
            # not merely as a new heading for the next person.  If another
            # missing-person heading begins immediately after this name, treat
            # it as introducing a different target and do not let later status
            # words leak backward onto the current name.
            introduces_next_target = any(
                term in after[:100]
                for term in ("person missing", "missing person", "missing persons")
            )
            if introduces_next_target:
                start = pos + len(name)
                continue

            for pattern in after_name_patterns:
                match = re.search(pattern, after)
                if not match:
                    continue
                prefix = after[:match.start()].strip(" |:-–—,.;()[]")
                # If the first status hit is the phrase "person missing" /
                # "missing person" after another name, it is likely a heading
                # introducing the next person, not a predicate for this name.
                status_tail = after[match.start():match.start() + 30]
                if (
                    status_tail.startswith("missing")
                    and re.match(r"^\s*(?:person|persons)\b", status_tail[len("missing"):])
                ):
                    continue
                if pattern == r"\bmissing\b" and re.search(r"(?:^|\s)persons?$", prefix):
                    # ``Author Name | PERSON MISSING Target Name``: the word
                    # missing introduces the target that follows, not the author.
                    continue
                if len(prefix) <= 90:
                    return True
            start = pos + len(name)

    return False

def _evidence_sources(
    candidate: DiscoveryCandidate,
    *,
    source_post_text: str,
    ocr_text: str,
) -> dict[str, str]:
    return {
        "title": candidate.title or "",
        "indexed_snippet": candidate.snippet or "",
        "public_post_text": source_post_text or "",
        "ocr_text": ocr_text or "",
    }


def _filter_evidence_verified_people(
    raw_payload: dict[str, Any],
    candidate: DiscoveryCandidate,
    *,
    source_post_text: str,
    ocr_text: str,
) -> tuple[dict[str, Any], list[str]]:
    """Fail closed on AI-proposed names without direct missing-status evidence.

    Structured Outputs makes the JSON shape reliable, but it does not by itself
    prove that every extracted name has the right role.  This second deterministic
    gate is deliberately conservative because creating a false missing-person record
    is costlier than asking an operator to review an omitted ambiguous name.
    """
    people = raw_payload.get("people")
    if not isinstance(people, list):
        return {**raw_payload, "people": []}, ["AI response did not contain a people list"]

    sources = _evidence_sources(
        candidate,
        source_post_text=source_post_text,
        ocr_text=ocr_text,
    )
    accepted: list[dict[str, Any]] = []
    rejected: list[str] = []
    seen_people: set[str] = set()

    for item in people:
        if not isinstance(item, dict):
            rejected.append("unnamed object: invalid person structure")
            continue

        name = str(item.get("name") or "").strip()
        name_ne = str(item.get("name_ne") or "").strip()
        label = name or name_ne or "unnamed person"
        source_name = str(item.get("evidence_source") or "").strip()
        excerpt = str(item.get("missing_status_evidence") or "").strip()

        if not (name or name_ne):
            rejected.append(f"{label}: no explicit written name")
            continue
        if not excerpt:
            rejected.append(f"{label}: no direct missing-status evidence")
            continue
        if len(excerpt) > 500:
            rejected.append(f"{label}: evidence excerpt was not tightly scoped")
            continue
        if not _has_missing_status_language(excerpt):
            rejected.append(f"{label}: evidence does not explicitly establish missing/out-of-contact status")
            continue

        person_names = [value for value in (name, name_ne) if value]
        excerpt_key = _name_key(excerpt)
        candidate_name_keys = [key for key in (_name_key(name), _name_key(name_ne)) if key]
        if not any(key in excerpt_key for key in candidate_name_keys):
            rejected.append(f"{label}: evidence excerpt does not contain that person's written name")
            continue
        if not _has_direct_missing_relation(excerpt, person_names):
            rejected.append(f"{label}: missing-status wording is not directly tied to that name")
            continue

        if source_name != "source_image_text":
            source_text = sources.get(source_name)
            if source_text is None:
                rejected.append(f"{label}: unknown evidence source")
                continue
            normalized_excerpt = _match_text(excerpt)
            normalized_source = _match_text(source_text)
            if not normalized_excerpt or normalized_excerpt not in normalized_source:
                rejected.append(f"{label}: quoted evidence was not found in the stated source")
                continue

        # De-duplicate exact written identities from one model response.  Prefer the
        # first object because it is normally the more complete one.
        identity = _name_key(name) or _name_key(name_ne)
        if identity and identity in seen_people:
            rejected.append(f"{label}: duplicate AI object for the same written name")
            continue
        if identity:
            seen_people.add(identity)

        accepted.append(item)

    result = {**raw_payload, "people": accepted}
    return result, rejected

def _build_request_payload(
    disaster: Disaster,
    candidate: DiscoveryCandidate,
    *,
    source_post_text: str = "",
    ocr_text: str = "",
    source_image_url: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": _evidence_text(
                disaster,
                candidate,
                source_post_text=source_post_text,
                ocr_text=ocr_text,
            ),
        }
    ]
    if source_image_url and is_allowed_public_image_url(source_image_url):
        content.append(
            {
                "type": "input_image",
                "image_url": source_image_url,
                "detail": "high",
            }
        )

    return {
        "model": model or str(os.getenv("OPENAI_PREFILL_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "instructions": _instructions(),
        "input": [
            {
                "role": "user",
                "content": content,
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "missing_person_prefill",
                "strict": True,
                "schema": _schema(),
            }
        },
        "max_output_tokens": 4000,
        "store": False,
    }


def _extract_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    refusal_texts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                text = content["text"].strip()
                if text:
                    return text
            if content.get("type") == "refusal" and isinstance(content.get("refusal"), str):
                refusal_texts.append(content["refusal"].strip())

    if refusal_texts:
        raise OpenAIPrefillError("The AI could not complete this extraction from the supplied evidence.")

    status = str(payload.get("status") or "").strip().casefold()
    if status == "incomplete":
        reason = ((payload.get("incomplete_details") or {}).get("reason") or "unknown reason")
        raise OpenAIPrefillError(f"AI extraction was incomplete: {reason}.")

    raise OpenAIPrefillError("OpenAI returned no structured prefill text.")


def _friendly_api_error(response: httpx.Response) -> OpenAIPrefillError:
    status = response.status_code
    if status in {401, 403}:
        return OpenAIPrefillError(
            "OpenAI API authentication failed. Check the server OPENAI_API_KEY."
        )
    if status == 429:
        return OpenAIPrefillError(
            "OpenAI API rate, billing, or spending limit was reached. Check the API project balance and limits."
        )
    if status >= 500:
        return OpenAIPrefillError(
            "OpenAI is temporarily unavailable. The candidate was not changed; try again later."
        )

    detail = ""
    try:
        body = response.json()
        message = ((body.get("error") or {}).get("message") or "") if isinstance(body, dict) else ""
        if message:
            detail = f" {str(message)[:240]}"
    except ValueError:
        pass
    return OpenAIPrefillError(
        f"OpenAI prefill request failed with HTTP {status}.{detail}".strip()
    )


async def generate_openai_candidate_prefill(
    disaster: Disaster,
    candidate: DiscoveryCandidate,
    *,
    source_post_text: str = "",
    ocr_text: str = "",
    source_image_url: str | None = None,
) -> dict[str, Any]:
    key = str(os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise OpenAIPrefillError(
            "Backend AI prefill is not configured. Set OPENAI_API_KEY on the server first."
        )

    model = str(os.getenv("OPENAI_PREFILL_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    try:
        timeout_seconds = float(os.getenv("OPENAI_PREFILL_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
    except ValueError:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    request_payload = _build_request_payload(
        disaster,
        candidate,
        source_post_text=source_post_text,
        ocr_text=ocr_text,
        source_image_url=source_image_url,
        model=model,
    )

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=10.0)) as client:
            response = await client.post(
                OPENAI_RESPONSES_URL,
                headers=headers,
                json=request_payload,
            )
    except httpx.HTTPError as exc:
        raise OpenAIPrefillError(
            "Could not reach OpenAI for AI prefill. The candidate was not changed."
        ) from exc

    if response.status_code != 200:
        raise _friendly_api_error(response)

    try:
        api_payload = response.json()
    except ValueError as exc:
        raise OpenAIPrefillError("OpenAI returned an unreadable response.") from exc

    output_text = _extract_output_text(api_payload)

    # Structured output should always be valid JSON.  Parse it directly first so
    # the backend can enforce the per-person evidence proof before the generic
    # form normalizer strips those proof fields.
    try:
        structured = json.loads(output_text)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OpenAIPrefillError(
            "OpenAI returned structured output that could not be verified safely."
        ) from exc
    if not isinstance(structured, dict):
        raise OpenAIPrefillError("OpenAI returned an invalid structured prefill object.")

    verified, rejected = _filter_evidence_verified_people(
        structured,
        candidate,
        source_post_text=source_post_text,
        ocr_text=ocr_text,
    )

    try:
        normalized = parse_candidate_chatgpt_prefill(
            json.dumps(verified, ensure_ascii=False)
        )
    except ValueError as exc:
        note = str(verified.get("source_notes") or "").strip()
        suffix = f" Source note: {note}" if note else ""
        if rejected:
            suffix += f" Evidence gate rejected {len(rejected)} proposed name(s)."
        raise OpenAIPrefillError(
            "No AI-proposed person passed the direct missing-status evidence check." + suffix
        ) from exc

    # Preserve the proof excerpt for operator visibility without storing it as a
    # master-person field.  The batch parser safely ignores these extra keys.
    verified_people = verified.get("people") or []
    for index, person in enumerate(normalized.get("people") or []):
        if index >= len(verified_people) or not isinstance(verified_people[index], dict):
            continue
        proof = verified_people[index]
        person["evidence_source"] = proof.get("evidence_source")
        person["missing_status_evidence"] = proof.get("missing_status_evidence")

    if rejected:
        base_note = str(normalized.get("source_notes") or "").strip()
        gate_note = (
            f"Evidence gate excluded {len(rejected)} proposed name(s) that were not "
            "directly established as missing."
        )
        normalized["source_notes"] = f"{base_note} {gate_note}".strip()

    usage = api_payload.get("usage") if isinstance(api_payload.get("usage"), dict) else {}
    return {
        **normalized,
        "model": str(api_payload.get("model") or model),
        "usage": {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
    }
