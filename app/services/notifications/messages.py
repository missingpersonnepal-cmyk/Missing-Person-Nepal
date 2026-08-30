from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ...config import settings
from ...models import MissingPerson

CASE_UPDATED = "CASE_UPDATED"
FOUND_ALIVE = "FOUND_ALIVE"
IDENTIFIED_DECEASED = "IDENTIFIED_DECEASED"


@dataclass(frozen=True)
class RenderedMessage:
    subject: str | None
    body: str


def public_case_link(person: MissingPerson) -> str:
    return f"{settings.public_base_url}/person/{person.case_number}"


def render_message(
    person: MissingPerson,
    event_type: str,
    channel: str,
    *,
    event_date: datetime | None = None,
    update_note: str | None = None,
) -> RenderedMessage:
    name = person.name
    if event_type == FOUND_ALIVE:
        sms = (
            f"{name} has been found. Please check the Missing Persons Hub or contact "
            "the relevant authority for further information."
        )
        subject = f"Case update: {name}"
    elif event_type == IDENTIFIED_DECEASED:
        sms = (
            f"There has been a movement in the file of {name}. Please contact the "
            "local authority for further information."
        )
        subject = f"Case file movement: {name}"
    else:
        sms = (
            f"There has been an update to the missing-person file for {name}. Please "
            "check the Missing Persons Hub or contact the relevant authority."
        )
        subject = f"Missing-person file update: {name}"

    if channel == "sms":
        return RenderedMessage(subject=None, body=sms)

    lines = [
        sms,
        "",
        f"Name: {name}",
        f"Case number: {person.case_number}",
        f"Case link: {public_case_link(person)}",
    ]
    if event_date:
        lines.append(f"Event date: {event_date.date().isoformat()}")
    if update_note:
        lines.extend(["", update_note])
    return RenderedMessage(subject=subject, body="\n".join(lines))
