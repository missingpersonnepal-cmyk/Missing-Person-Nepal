from __future__ import annotations

import json

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


def build_candidate_chatgpt_prefill_prompt(
    disaster: Disaster,
    candidate: DiscoveryCandidate,
    *,
    source_post_text: str = "",
    ocr_text: str = "",
) -> str:
    """Build a zero-API-cost ChatGPT prefill prompt for one reviewed source.

    The browser copies this prompt into an interactive ChatGPT session.  The
    local application never sends the evidence to an AI API automatically.
    """
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

The administrator has already marked this public source as RELEVANT. Your job is to extract the missing-person details from the supplied public textual evidence, not to decide whether the source is relevant.

STRICT SAFETY AND EVIDENCE RULES
- Use only the supplied title, indexed snippet, public post text, and OCR text.
- Never identify a person from a photograph or face.
- Never infer gender, age, identity, ethnicity, relationship, clothing, location, phone number, or any other attribute from appearance.
- Do not invent, guess, translate a name unless the source explicitly provides that form, or merge details belonging to different people.
- If a field cannot be tied to a specific named person, return null for that field.
- Gender must be "Male", "Female", or null, and only when explicitly stated in textual evidence.
- Keep dates as YYYY-MM-DD only when the evidence supports an exact Gregorian date. Do not convert vague relative wording such as "yesterday" unless an exact reference date is explicitly present in the evidence.
- Keep times as HH:MM only when explicitly stated.
- Preserve useful location wording, workplace/address clues, family relationship details, identifying textual details, and public contact details.
- A single post can report MULTIPLE missing people. Return every explicitly named missing person as a separate object.
- Do not create a separate person merely because a relative/contact name appears. Include a person only when the evidence actually reports that person as missing/out of contact.
- If the source says a family/group is missing but individual names cannot be separated safely, return the explicitly named people only and explain the group wording in identification_details.
- Public phone/contact numbers may be returned. Do not expose private information that is not present in the supplied public evidence.

RETURN FORMAT
Return JSON only. No markdown fences and no commentary.

{{
  "people": [
    {{
      "name": "string or null",
      "name_ne": "string or null",
      "age": 0,
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

For age, use an integer or null, not 0 when unknown.

SOURCE EVIDENCE
{payload}
"""
