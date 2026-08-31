"""case verification metadata and timeline"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    for table in ("mp_missing_people", "mp_submissions"):
        op.add_column(table, sa.Column("source_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.add_column(table, sa.Column("verification_confidence", sa.String(length=20), nullable=True))
        op.add_column(table, sa.Column("verified_by", sa.String(length=100), nullable=True))
        op.add_column(table, sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("approval_notes", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("location_uncertain", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "mp_case_timeline",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["mp_missing_people.id"]),
    )
    op.create_index("ix_mp_case_timeline_person_id", "mp_case_timeline", ["person_id"])
    op.create_index("ix_mp_case_timeline_event_type", "mp_case_timeline", ["event_type"])
    op.create_index("ix_mp_case_timeline_created_at", "mp_case_timeline", ["created_at"])

def downgrade() -> None:
    op.drop_table("mp_case_timeline")
    for table in ("mp_submissions", "mp_missing_people"):
        for column in ("location_uncertain", "approval_notes", "verified_at", "verified_by", "verification_confidence", "source_confirmed"):
            op.drop_column(table, column)
