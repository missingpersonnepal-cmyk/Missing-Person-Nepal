from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Disaster,
    DiscoveryCandidate,
    DiscoverySearchTag,
    DiscoverySourceSeed,
)


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


def normalize_facebook_source_scope(value: str) -> str | None:
    """Normalize a public Facebook page/group URL or bare scope."""
    raw = str(value or "").strip()
    if not raw:
        return None

    if "://" not in raw and not raw.casefold().startswith("facebook.com/"):
        scope = raw.strip().strip("/")
        if scope and " " not in scope:
            return scope
        return None

    if "://" not in raw:
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
    except ValueError:
        return None

    host = (parsed.hostname or "").casefold().rstrip(".")
    if not (host == "facebook.com" or host.endswith(".facebook.com")):
        return None

    parts = [part.strip() for part in parsed.path.split("/") if part.strip()]
    if not parts:
        return None

    if parts[0].casefold() == "groups" and len(parts) >= 2:
        return f"groups/{parts[1]}"

    blocked = {
        "watch", "reel", "reels", "photo", "photos", "share",
        "story.php", "permalink.php", "plugins",
    }
    if parts[0].casefold() in blocked:
        return None

    return parts[0]


def source_url_for_scope(scope: str) -> str:
    return f"https://www.facebook.com/{scope.strip('/')}/"


def priority_manual_searches(disaster: Disaster) -> list[dict[str, str]]:
    """Source-level manual investigations shown to an operator."""
    event_root = _event_root(disaster)
    locations = disaster.locations()
    top_location = locations[0] if locations else event_root

    rows: list[dict[str, str]] = []
    for source in PRIORITY_SOURCES:
        prefix = _source_prefix(source)
        query = f'{prefix} "{event_root}" "missing person"'
        rows.append(
            {
                "label": source.label,
                "tier": source.tier,
                "query": " ".join(query.split()),
                "source_url": (
                    source_url_for_scope(source.facebook_scope)
                    if source.facebook_scope
                    else ""
                ),
                "secondary_query": " ".join(
                    f'{prefix} "{top_location}" "out of contact"'.split()
                ),
            }
        )
    return rows


def priority_wide_queries(
    disaster: Disaster,
    extra_sources: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Reserved high-value source queries for automated Serper discovery."""
    event_root = _event_root(disaster)
    after = (disaster.start_date - timedelta(days=1)).isoformat()
    date_filter = f"after:{after}"

    queries: list[str] = []
    for source in PRIORITY_SOURCES:
        prefix = _source_prefix(source)
        queries.append(
            " ".join(
                f'{prefix} "{event_root}" "missing person" {date_filter}'.split()
            )
        )

    for label, scope in extra_sources or []:
        prefix = f"site:facebook.com/{scope}"
        queries.append(
            " ".join(
                f'{prefix} "{event_root}" "missing person" {date_filter}'.split()
            )
        )
    return queries


def priority_source_scopes() -> list[str]:
    return [
        source.facebook_scope
        for source in PRIORITY_SOURCES
        if source.facebook_scope
    ]


def user_search_tags(
    db: Session,
    disaster_id: int,
    platform: str = "facebook",
) -> list[DiscoverySearchTag]:
    return list(
        db.scalars(
            select(DiscoverySearchTag)
            .where(
                DiscoverySearchTag.disaster_id == disaster_id,
                DiscoverySearchTag.platform == platform,
                DiscoverySearchTag.active.is_(True),
            )
            .order_by(DiscoverySearchTag.created_at.asc())
        ).all()
    )


def user_source_seeds(
    db: Session,
    disaster_id: int,
    platform: str = "facebook",
) -> list[DiscoverySourceSeed]:
    return list(
        db.scalars(
            select(DiscoverySourceSeed)
            .where(
                DiscoverySourceSeed.disaster_id == disaster_id,
                DiscoverySourceSeed.platform == platform,
                DiscoverySourceSeed.active.is_(True),
            )
            .order_by(DiscoverySourceSeed.created_at.asc())
        ).all()
    )


def custom_tag_queries(
    disaster: Disaster,
    tags: list[str],
) -> list[str]:
    event_root = _event_root(disaster)
    locations = disaster.locations()
    top_locations = locations[:2] or [event_root]
    rows: list[str] = []
    for raw in tags:
        tag = " ".join(str(raw or "").split())
        if not tag:
            continue
        rows.append(f'site:facebook.com "{event_root}" "{tag}"')
        for location in top_locations:
            rows.append(f'site:facebook.com "{location}" "{tag}"')
    # stable dedupe
    return list(dict.fromkeys(rows))


def discovered_source_activity(
    db: Session,
    disaster_id: int,
    *,
    minimum_posts: int = 2,
) -> list[dict[str, object]]:
    """Rank Facebook pages/groups repeatedly appearing in candidate results.

    This is a discovery hint, not trust. A source is promoted into the manual
    source list only after an operator explicitly adds it.
    """
    rows = list(
        db.scalars(
            select(DiscoveryCandidate)
            .where(
                DiscoveryCandidate.disaster_id == disaster_id,
                DiscoveryCandidate.platform == "facebook",
                DiscoveryCandidate.status.notin_(["irrelevant", "rejected"]),
            )
            .order_by(DiscoveryCandidate.found_at.desc())
            .limit(1500)
        ).all()
    )

    stats: dict[str, dict[str, object]] = {}
    for row in rows:
        scope = normalize_facebook_source_scope(row.url)
        if not scope:
            continue
        item = stats.setdefault(
            scope,
            {"scope": scope, "posts": 0, "confirmed": 0},
        )
        item["posts"] = int(item["posts"]) + 1
        if row.status in {"relevant", "reviewed"}:
            item["confirmed"] = int(item["confirmed"]) + 1

    output = [
        item for item in stats.values()
        if int(item["posts"]) >= minimum_posts
    ]
    output.sort(
        key=lambda item: (
            -int(item["confirmed"]),
            -int(item["posts"]),
            str(item["scope"]).casefold(),
        )
    )
    return output[:30]
