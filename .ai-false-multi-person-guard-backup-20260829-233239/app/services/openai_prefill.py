from __future__ import annotations

import json
import os
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

Safety and evidence rules:
- Never identify a person from a face or photograph.
- If an image is supplied, use it only to read visible written/printed text. Do not infer identity, gender, age, ethnicity, clothing, location, relationship, or any other attribute from appearance.
- Never invent or guess facts.
- Never translate or alter a person's name unless that exact form is explicitly present in the supplied evidence.
- Keep each person's details separate. Do not merge details between people.
- A contact/relative named only as the person to call is not a missing person unless the evidence explicitly says that person is missing.
- Return every explicitly named missing person in the post, including named families or multiple people.
- Gender must be Male, Female, or null, and only when explicitly stated in textual evidence.
- Dates must be exact Gregorian YYYY-MM-DD values only when explicitly supported. Do not convert Bikram Sambat dates or relative dates.
- Times must be HH:MM only when explicitly stated.
- Public phone/contact numbers may be returned only when present in the supplied public evidence.
- Preserve useful workplace, address, family relationship, identifying, and last-seen wording in identification_details when it belongs to that specific person.
- If no usable named missing person can be established, return an empty people array and explain the evidence limitation in source_notes.

Re-scan the evidence once before returning so that no explicitly named missing person or public contact detail is missed."""


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
    try:
        normalized = parse_candidate_chatgpt_prefill(output_text)
    except ValueError as exc:
        raise OpenAIPrefillError(
            "OpenAI returned structured output that could not be normalized safely."
        ) from exc

    if not normalized.get("people"):
        raise OpenAIPrefillError(
            normalized.get("source_notes")
            or "The AI did not find an explicitly named missing person in the supplied evidence."
        )

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
