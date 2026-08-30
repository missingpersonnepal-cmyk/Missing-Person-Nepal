"""notification subscriptions and outbox

Revision ID: f31b6c4d9201
Revises: 9b7d4c2a18f0
Create Date: 2026-08-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f31b6c4d9201"
down_revision: Union[str, None] = "9b7d4c2a18f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mp_notification_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["mp_missing_people.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "channel", "destination", name="uq_mp_notification_subscription"),
    )
    op.create_index("ix_mp_notification_subscriptions_person_id", "mp_notification_subscriptions", ["person_id"])
    op.create_index("ix_mp_notification_subscriptions_channel", "mp_notification_subscriptions", ["channel"])
    op.create_index("ix_mp_notification_subscriptions_active", "mp_notification_subscriptions", ["active"])

    op.create_table(
        "mp_notification_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["person_id"], ["mp_missing_people.id"]),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["mp_notification_subscriptions.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subscription_id",
            "idempotency_key",
            name="uq_mp_notification_event_delivery",
        ),
    )
    op.create_index("ix_mp_notification_outbox_person_id", "mp_notification_outbox", ["person_id"])
    op.create_index("ix_mp_notification_outbox_subscription_id", "mp_notification_outbox", ["subscription_id"])
    op.create_index("ix_mp_notification_outbox_event_type", "mp_notification_outbox", ["event_type"])
    op.create_index("ix_mp_notification_outbox_idempotency_key", "mp_notification_outbox", ["idempotency_key"])
    op.create_index("ix_mp_notification_outbox_channel", "mp_notification_outbox", ["channel"])
    op.create_index("ix_mp_notification_outbox_status", "mp_notification_outbox", ["status"])


def downgrade() -> None:
    op.drop_index("ix_mp_notification_outbox_status", table_name="mp_notification_outbox")
    op.drop_index("ix_mp_notification_outbox_channel", table_name="mp_notification_outbox")
    op.drop_index("ix_mp_notification_outbox_event_type", table_name="mp_notification_outbox")
    op.drop_index("ix_mp_notification_outbox_idempotency_key", table_name="mp_notification_outbox")
    op.drop_index("ix_mp_notification_outbox_subscription_id", table_name="mp_notification_outbox")
    op.drop_index("ix_mp_notification_outbox_person_id", table_name="mp_notification_outbox")
    op.drop_table("mp_notification_outbox")
    op.drop_index("ix_mp_notification_subscriptions_active", table_name="mp_notification_subscriptions")
    op.drop_index("ix_mp_notification_subscriptions_channel", table_name="mp_notification_subscriptions")
    op.drop_index("ix_mp_notification_subscriptions_person_id", table_name="mp_notification_subscriptions")
    op.drop_table("mp_notification_subscriptions")
