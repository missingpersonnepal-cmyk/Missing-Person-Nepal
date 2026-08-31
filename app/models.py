from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Disaster(Base):
    __tablename__ = "mp_disasters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    disaster_type: Mapped[str] = mapped_column(String(50), default="flood")
    start_date: Mapped[date] = mapped_column(Date)
    affected_locations: Mapped[str] = mapped_column(Text, default="")
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    boundary_geojson: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    people: Mapped[list["MissingPerson"]] = relationship(back_populates="disaster")

    def locations(self) -> list[str]:
        return [x.strip() for x in self.affected_locations.splitlines() if x.strip()]


class MissingPerson(Base):
    __tablename__ = "mp_missing_people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_number: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    disaster_id: Mapped[int] = mapped_column(ForeignKey("mp_disasters.id"), index=True)

    name: Mapped[str] = mapped_column(String(255), index=True)
    name_ne: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(30), nullable=True)
    photo_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    residential_address_private: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    last_seen_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    last_seen_location: Mapped[str] = mapped_column(Text, default="", index=True)
    clothing: Mapped[str | None] = mapped_column(Text, nullable=True)
    identification_details: Mapped[str | None] = mapped_column(Text, nullable=True)

    public_contact_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    private_contact_number: Mapped[str | None] = mapped_column(String(80), nullable=True)

    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    disaster: Mapped[Disaster] = relationship(back_populates="people")
    sources: Mapped[list["Source"]] = relationship(back_populates="person", cascade="all, delete-orphan")


class Source(Base):
    __tablename__ = "mp_sources"
    __table_args__ = (UniqueConstraint("person_id", "url", name="uq_mp_source_person_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("mp_missing_people.id"), index=True)
    platform: Mapped[str] = mapped_column(String(40), default="website", index=True)
    url: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    person: Mapped[MissingPerson] = relationship(back_populates="sources")


class Submission(Base):
    __tablename__ = "mp_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disaster_id: Mapped[int | None] = mapped_column(ForeignKey("mp_disasters.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), default="missing_report")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("mp_missing_people.id"), nullable=True)

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_ne: Mapped[str | None] = mapped_column(String(255), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(30), nullable=True)
    photo_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    residential_address_private: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_seen_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    last_seen_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    clothing: Mapped[str | None] = mapped_column(Text, nullable=True)
    identification_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_contact_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)

    reporter_name_private: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reporter_phone_private: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reporter_relationship: Mapped[str | None] = mapped_column(String(100), nullable=True)
    social_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscoveryCandidate(Base):
    __tablename__ = "mp_discovery_candidates"
    __table_args__ = (UniqueConstraint("disaster_id", "url", name="uq_mp_discovery_event_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disaster_id: Mapped[int | None] = mapped_column(ForeignKey("mp_disasters.id"), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(40), default="facebook", index=True)
    query: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscoverySearchTag(Base):
    __tablename__ = "mp_discovery_search_tags"
    __table_args__ = (
        UniqueConstraint(
            "disaster_id", "platform", "tag",
            name="uq_mp_discovery_search_tag",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disaster_id: Mapped[int] = mapped_column(ForeignKey("mp_disasters.id"), index=True)
    platform: Mapped[str] = mapped_column(String(40), default="facebook", index=True)
    tag: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscoverySourceSeed(Base):
    __tablename__ = "mp_discovery_source_seeds"
    __table_args__ = (
        UniqueConstraint(
            "disaster_id", "platform", "scope",
            name="uq_mp_discovery_source_seed",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disaster_id: Mapped[int] = mapped_column(ForeignKey("mp_disasters.id"), index=True)
    platform: Mapped[str] = mapped_column(String(40), default="facebook", index=True)
    label: Mapped[str] = mapped_column(String(255))
    scope: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PersonCaseState(Base):
    __tablename__ = "mp_person_case_states"

    person_id: Mapped[int] = mapped_column(
        ForeignKey("mp_missing_people.id"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="missing", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class CaseTimeline(Base):
    __tablename__ = "mp_case_timeline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("mp_missing_people.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class NotificationSubscription(Base):
    __tablename__ = "mp_notification_subscriptions"
    __table_args__ = (
        UniqueConstraint("person_id", "channel", "destination", name="uq_mp_notification_subscription"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("mp_missing_people.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), index=True)
    destination: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class NotificationOutbox(Base):
    __tablename__ = "mp_notification_outbox"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "idempotency_key",
            name="uq_mp_notification_event_delivery",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(
        ForeignKey("mp_missing_people.id"), index=True
    )
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("mp_notification_subscriptions.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200))

    @property
    def dedupe_key(self) -> str:
        """Backward-compatible alias for the event-instance idempotency key."""
        return self.idempotency_key

    @dedupe_key.setter
    def dedupe_key(self, value: str) -> None:
        self.idempotency_key = value

    channel: Mapped[str] = mapped_column(String(20), index=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AdminUser(Base):
    __tablename__ = "mp_admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(30), default="super_admin", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "mp_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_username: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
