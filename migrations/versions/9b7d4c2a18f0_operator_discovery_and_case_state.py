"""operator discovery configuration and person case state

Revision ID: 9b7d4c2a18f0
Revises: 27a3d918d44c
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9b7d4c2a18f0"
down_revision: Union[str, None] = "27a3d918d44c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mp_discovery_search_tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("disaster_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("tag", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["disaster_id"], ["mp_disasters.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("disaster_id", "platform", "tag", name="uq_mp_discovery_search_tag"),
    )
    op.create_index("ix_mp_discovery_search_tags_disaster_id", "mp_discovery_search_tags", ["disaster_id"])
    op.create_index("ix_mp_discovery_search_tags_platform", "mp_discovery_search_tags", ["platform"])
    op.create_index("ix_mp_discovery_search_tags_active", "mp_discovery_search_tags", ["active"])

    op.create_table(
        "mp_discovery_source_seeds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("disaster_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["disaster_id"], ["mp_disasters.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("disaster_id", "platform", "scope", name="uq_mp_discovery_source_seed"),
    )
    op.create_index("ix_mp_discovery_source_seeds_disaster_id", "mp_discovery_source_seeds", ["disaster_id"])
    op.create_index("ix_mp_discovery_source_seeds_platform", "mp_discovery_source_seeds", ["platform"])
    op.create_index("ix_mp_discovery_source_seeds_active", "mp_discovery_source_seeds", ["active"])

    op.create_table(
        "mp_person_case_states",
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["mp_missing_people.id"]),
        sa.PrimaryKeyConstraint("person_id"),
    )
    op.create_index("ix_mp_person_case_states_status", "mp_person_case_states", ["status"])


def downgrade() -> None:
    op.drop_index("ix_mp_person_case_states_status", table_name="mp_person_case_states")
    op.drop_table("mp_person_case_states")
    op.drop_index("ix_mp_discovery_source_seeds_active", table_name="mp_discovery_source_seeds")
    op.drop_index("ix_mp_discovery_source_seeds_platform", table_name="mp_discovery_source_seeds")
    op.drop_index("ix_mp_discovery_source_seeds_disaster_id", table_name="mp_discovery_source_seeds")
    op.drop_table("mp_discovery_source_seeds")
    op.drop_index("ix_mp_discovery_search_tags_active", table_name="mp_discovery_search_tags")
    op.drop_index("ix_mp_discovery_search_tags_platform", table_name="mp_discovery_search_tags")
    op.drop_index("ix_mp_discovery_search_tags_disaster_id", table_name="mp_discovery_search_tags")
    op.drop_table("mp_discovery_search_tags")
