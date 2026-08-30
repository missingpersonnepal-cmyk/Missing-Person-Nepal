from __future__ import annotations

import json
from typing import Any, Iterable

from ..models import Disaster, DiscoveryCandidate


def build_free_ai_review_prompt(
    disaster: Disaster,
    candidates: Iterable[DiscoveryCandidate],
) -> str:
    """Build a manual ChatGPT Free review prompt.

    This function makes no API call and has no token billing.
    """
    candidate_payload = []

    for candidate in list(candidates)[:100]:
        candidate_payload.append(
            {
                "candidate_id": candidate.id,
                "platform": candidate.platform,
                "url": candidate.url,
                "title": candidate.title or "",
                "snippet": candidate.snippet or "",
                "search_query": candidate.query or "",
            }
        )

    payload = json.dumps(
        candidate_payload,
        ensure_ascii=False,
        indent=2,
    )

    locations = disaster.locations()

    return f"""You are assisting an administrator of a Nepal disaster missing-person registry.

EVENT
Name: {disaster.name}
Type: {disaster.disaster_type}
Start date: {disaster.start_date.isoformat()}
Affected locations: {", ".join(locations) if locations else disaster.name}

TASK

Review the public-web discovery candidates below.

Your objective is NOT to collect general news articles.

ACCEPT only results that concern:
- a specific missing person;
- a named missing family or multiple named people;
- a missing-person poster;
- a direct public appeal to locate someone;
- a person described as out of contact / सम्पर्कविहीन / बेपत्ता / हराएको;
- a credible missing-person list containing actual people.

REJECT:
- general flood news;
- death toll stories;
- rescue-operation updates;
- articles saying only that an unspecified number of people are missing;
- unrelated disasters;
- generic support groups;
- Facebook page/group homepages without a specific missing-person report;
- results with no useful person-level evidence.

You may inspect a supplied PUBLIC URL or use web search if available to you.

Never log into a private service.
Never access closed/private groups.
Never bypass access controls.
Never identify a person from a photograph.
Do not infer identity from an image.
Use only textual/publicly stated information.

If the URL cannot be inspected, use only the supplied title/snippet.

DO NOT INVENT INFORMATION.

A single Facebook post may contain MULTIPLE missing people.
Return each person separately inside that candidate's "people" array.

For every accepted person extract only information supported by the source:
- name
- name_ne
- age
- gender
- last_seen_date in YYYY-MM-DD when known
- last_seen_time in HH:MM when known
- last_seen_location
- clothing
- identification_details
- public_contact_number
- image_url

For image_url:
- return a DIRECT public image URL only when the public post clearly
  associates that image/poster with the specific missing-person report;
- do not identify or recognize a person from the photograph;
- do not guess that somebody shown in an image is the named person;
- if the image-to-person association is unclear, return null;
- if only the Facebook post URL is available and no direct public image
  URL is available, return null.

If a field is unknown, return null.

Return ONLY valid JSON.
No Markdown fences.
No explanatory prose outside the JSON.

Required format:

{{
  "results": [
    {{
      "candidate_id": 123,
      "decision": "accept",
      "confidence": 0.95,
      "reason": "Specific named missing-person notice",
      "people": [
        {{
          "name": "Example Person",
          "name_ne": null,
          "age": 32,
          "gender": null,
          "last_seen_date": null,
          "last_seen_time": null,
          "last_seen_location": "Timure",
          "clothing": null,
          "identification_details": null,
          "public_contact_number": "98XXXXXXXX",
          "image_url": null
        }}
      ]
    }},
    {{
      "candidate_id": 124,
      "decision": "reject",
      "confidence": 0.99,
      "reason": "General flood news",
      "people": []
    }},
    {{
      "candidate_id": 125,
      "decision": "uncertain",
      "confidence": 0.50,
      "reason": "Not enough public information",
      "people": []
    }}
  ]
}}

IMPORTANT:
candidate_id must remain exactly the candidate_id supplied below.
Do not create new candidate IDs.
Do not change source URLs.

DISCOVERY CANDIDATES

{payload}
"""


def parse_free_ai_review(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("AI review is not valid JSON") from exc

    if not isinstance(data, dict):
        raise ValueError("AI review must be a JSON object")

    results = data.get("results")

    if not isinstance(results, list):
        raise ValueError("AI review must contain a results array")

    normalized: list[dict[str, Any]] = []

    for item in results:
        if not isinstance(item, dict):
            continue

        try:
            candidate_id = int(item.get("candidate_id"))
        except (TypeError, ValueError):
            continue

        decision = str(
            item.get("decision") or ""
        ).strip().casefold()

        if decision not in {
            "accept",
            "reject",
            "uncertain",
        }:
            continue

        people = item.get("people")

        if not isinstance(people, list):
            people = []

        normalized.append(
            {
                "candidate_id": candidate_id,
                "decision": decision,
                "confidence": item.get("confidence"),
                "reason": str(
                    item.get("reason") or ""
                ).strip(),
                "people": [
                    person
                    for person in people
                    if isinstance(person, dict)
                ],
            }
        )

    return normalized
