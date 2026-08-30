from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from ..models import Disaster


@dataclass(frozen=True)
class PrioritySource:
    label: str
    facebook_scope: str | None = None
    tier: str = "monitored"


# Public sources observed sharing person-level Rasuwa flood missing-person
# information. These are search seeds only. Their posts still pass the same
# person-level filters and human review as every other source.
PRIORITY_SOURCES: tuple[PrioritySource, ...] = (
    PrioritySource(
        "Saigrace Pokharel / Saigrace Official",
        "saigraceofficial",
        "high",
    ),
    PrioritySource(
        "Bikki Gurung",
        "Bikkigurungofficial",
        "high",
    ),
    PrioritySource(
        "Hydropower Diaries",
        None,
        "high",
    ),
    PrioritySource(
        "Medico Nepal",
        "MedicoNepalOfficial",
        "high",
    ),
    PrioritySource(
        "Engineers Vlogs",
        None,
        "monitored",
    ),
    PrioritySource(
        "Hamro Sharemarket",
        "hamrosharemarketofficial",
        "monitored",
    ),
    PrioritySource(
        "LoL NEPAL",
        None,
        "monitored",
    ),
    PrioritySource(
        "इन्जिनियरको ब्यथा अरुलाई के था",
        None,
        "monitored",
    ),
)


def _event_root(disaster: Disaster) -> str:
    return (
        disaster.name
        .replace("Flood", "")
        .replace("flood", "")
        .strip()
        or disaster.name
    )


def _source_prefix(source: PrioritySource) -> str:
    if source.facebook_scope:
        return f"site:facebook.com/{source.facebook_scope}"
    return f'site:facebook.com "{source.label}"'


def priority_manual_searches(
    disaster: Disaster,
) -> list[dict[str, str]]:
    """Queries shown to an operator for one-click manual investigation.

    Manual searches are intentionally a little broader than automated
    admission because a human is deciding what to add.
    """
    event_root = _event_root(disaster)
    locations = disaster.locations()
    top_location = locations[0] if locations else event_root

    rows: list[dict[str, str]] = []
    for source in PRIORITY_SOURCES:
        prefix = _source_prefix(source)

        for query in (
            f'{prefix} "{event_root}" "missing"',
            f'{prefix} "{top_location}" "out of contact"',
        ):
            rows.append(
                {
                    "label": source.label,
                    "tier": source.tier,
                    "query": " ".join(query.split()),
                    "source_url": (
                        f"https://www.facebook.com/{source.facebook_scope}/"
                        if source.facebook_scope
                        else ""
                    ),
                }
            )

    return rows


def priority_wide_queries(
    disaster: Disaster,
) -> list[str]:
    """Reserved high-value source queries for automated Serper discovery."""
    event_root = _event_root(disaster)
    after = (disaster.start_date - timedelta(days=1)).isoformat()
    date_filter = f"after:{after}"

    queries: list[str] = []

    # One query per source keeps this lane useful without swallowing the
    # 40-query global budget.
    for source in PRIORITY_SOURCES:
        prefix = _source_prefix(source)
        queries.append(
            " ".join(
                f'{prefix} "{event_root}" "missing person" {date_filter}'.split()
            )
        )

    return queries


def priority_source_scopes() -> list[str]:
    """Known Facebook scopes that can safely receive source-scoped searches."""
    return [
        source.facebook_scope
        for source in PRIORITY_SOURCES
        if source.facebook_scope
    ]
