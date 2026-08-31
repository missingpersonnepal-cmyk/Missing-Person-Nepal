"""geo coordinates for events and missing persons

Revision ID: b1c2d3e4f5a6
Revises: a4c2f5d8e901
Create Date: 2026-08-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a4c2f5d8e901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mp_disasters", sa.Column("center_lat", sa.Float(), nullable=True))
    op.add_column("mp_disasters", sa.Column("center_lon", sa.Float(), nullable=True))
    op.add_column("mp_missing_people", sa.Column("last_seen_lat", sa.Float(), nullable=True))
    op.add_column("mp_missing_people", sa.Column("last_seen_lon", sa.Float(), nullable=True))
    op.add_column("mp_submissions", sa.Column("last_seen_lat", sa.Float(), nullable=True))
    op.add_column("mp_submissions", sa.Column("last_seen_lon", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("mp_submissions", "last_seen_lon")
    op.drop_column("mp_submissions", "last_seen_lat")
    op.drop_column("mp_missing_people", "last_seen_lon")
    op.drop_column("mp_missing_people", "last_seen_lat")
    op.drop_column("mp_disasters", "center_lon")
    op.drop_column("mp_disasters", "center_lat")
