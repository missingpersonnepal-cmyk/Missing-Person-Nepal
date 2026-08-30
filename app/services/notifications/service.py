from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import MissingPerson, NotificationOutbox, NotificationSubscription, utcnow
from .email import get_email_provider
from .messages import CASE_UPDATED, FOUND_ALIVE, IDENTIFIED_DECEASED, render_message
from .sms import get_sms_provider

EVENT_TYPES = {CASE_UPDATED, FOUND_ALIVE, IDENTIFIED_DECEASED}
CHANNELS = {"sms", "email"}


def mask_destination(destination: str, channel: str) -> str:
    value = destination.strip()
    if channel == "email" and "@" in value:
        user, domain = value.split("@", 1)
        return f"{user[:1]}***@{domain}"
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 4:
        return f"{digits[:2]}******{digits[-2:]}"
    return "***"


def add_subscription(db: Session, person_id: int, channel: str, destination: str) -> NotificationSubscription:
    channel = channel.strip().casefold()
    destination = destination.strip()
    if channel not in CHANNELS or not destination:
        raise ValueError("Invalid notification subscription")
    existing = db.scalar(
        select(NotificationSubscription).where(
            NotificationSubscription.person_id == person_id,
            NotificationSubscription.channel == channel,
            func.lower(NotificationSubscription.destination) == destination.casefold(),
        )
    )
    if existing:
        existing.active = True
        existing.updated_at = utcnow()
        return existing
    row = NotificationSubscription(person_id=person_id, channel=channel, destination=destination, active=True)
    db.add(row)
    db.flush()
    return row


def enqueue_case_notifications(
    db: Session,
    person: MissingPerson,
    event_type: str,
    *,
    update_note: str | None = None,
) -> int:
    if event_type not in EVENT_TYPES:
        raise ValueError("Invalid notification event")
    subscriptions = db.scalars(
        select(NotificationSubscription).where(
            NotificationSubscription.person_id == person.id,
            NotificationSubscription.active.is_(True),
        )
    ).all()
    created = 0
    for subscription in subscriptions:
        message = render_message(person, event_type, subscription.channel, update_note=update_note)
        exists = db.scalar(
            select(NotificationOutbox.id).where(
                NotificationOutbox.person_id == person.id,
                NotificationOutbox.subscription_id == subscription.id,
                NotificationOutbox.event_type == event_type,
            )
        )
        if exists:
            continue
        db.add(
            NotificationOutbox(
                person_id=person.id,
                subscription_id=subscription.id,
                event_type=event_type,
                channel=subscription.channel,
                subject=message.subject,
                body=message.body,
            )
        )
        db.flush()
        created += 1
    return created


def retry_failed_notifications(db: Session, person_id: int | None = None) -> int:
    stmt = select(NotificationOutbox).where(NotificationOutbox.status == "failed")
    if person_id:
        stmt = stmt.where(NotificationOutbox.person_id == person_id)
    rows = db.scalars(stmt).all()
    for row in rows:
        row.status = "pending"
        row.last_error = None
    db.flush()
    return len(rows)


def cancel_pending_notifications(db: Session, person_id: int | None = None) -> int:
    stmt = select(NotificationOutbox).where(NotificationOutbox.status == "pending")
    if person_id:
        stmt = stmt.where(NotificationOutbox.person_id == person_id)
    rows = db.scalars(stmt).all()
    for row in rows:
        row.status = "cancelled"
    db.flush()
    return len(rows)


def drain_pending_notifications(db: Session, limit: int = 25) -> dict[str, int]:
    rows = db.scalars(
        select(NotificationOutbox)
        .where(NotificationOutbox.status == "pending")
        .order_by(NotificationOutbox.created_at)
        .limit(limit)
    ).all()
    sent = failed = skipped = 0
    for row in rows:
        subscription = db.get(NotificationSubscription, row.subscription_id)
        if subscription is None or not subscription.active:
            row.status = "cancelled"
            skipped += 1
            continue
        try:
            if row.channel == "sms":
                provider = get_sms_provider()
                if not provider.configured:
                    skipped += 1
                    continue
                result = provider.send(subscription.destination, row.body)
            else:
                provider = get_email_provider()
                if not provider.configured:
                    skipped += 1
                    continue
                result = provider.send(subscription.destination, row.subject or "Missing Persons Hub update", row.body)
            row.status = "sent"
            row.provider_message_id = result.provider_message_id
            row.sent_at = utcnow()
            row.last_error = None
            sent += 1
        except Exception as exc:
            row.status = "failed"
            row.attempts += 1
            row.last_error = str(exc)[:500]
            failed += 1
    db.flush()
    return {"sent": sent, "failed": failed, "skipped": skipped}
