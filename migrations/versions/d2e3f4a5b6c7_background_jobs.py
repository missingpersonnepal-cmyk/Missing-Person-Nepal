"""persist background job status"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table("mp_background_jobs", sa.Column("id", sa.String(length=36), primary_key=True), sa.Column("kind", sa.String(length=80), nullable=False), sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"), sa.Column("payload", sa.Text(), nullable=False, server_default="{}"), sa.Column("result", sa.Text(), nullable=False, server_default="{}"), sa.Column("error", sa.Text(), nullable=True), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_mp_background_jobs_kind", "mp_background_jobs", ["kind"])
    op.create_index("ix_mp_background_jobs_status", "mp_background_jobs", ["status"])
    op.create_index("ix_mp_background_jobs_created_at", "mp_background_jobs", ["created_at"])

def downgrade() -> None:
    op.drop_table("mp_background_jobs")
