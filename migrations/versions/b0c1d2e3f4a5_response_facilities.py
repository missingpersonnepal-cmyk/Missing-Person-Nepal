"""admin-managed response facilities"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table("mp_facilities", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(length=255), nullable=False), sa.Column("facility_type", sa.String(length=40), nullable=False), sa.Column("address", sa.Text(), nullable=True), sa.Column("contact", sa.String(length=120), nullable=True), sa.Column("capacity", sa.Integer(), nullable=True), sa.Column("lat", sa.Float(), nullable=False), sa.Column("lon", sa.Float(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_mp_facilities_name", "mp_facilities", ["name"])
    op.create_index("ix_mp_facilities_facility_type", "mp_facilities", ["facility_type"])
    op.create_index("ix_mp_facilities_active", "mp_facilities", ["active"])

def downgrade() -> None:
    op.drop_table("mp_facilities")
