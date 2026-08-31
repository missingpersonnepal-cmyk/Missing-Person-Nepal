"""multiple case photo evidence"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table("mp_person_photos", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("person_id", sa.Integer(), nullable=False), sa.Column("photo_path", sa.Text(), nullable=False), sa.Column("source", sa.String(length=255), nullable=True), sa.Column("consent_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("uploaded_by", sa.String(length=100), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["person_id"], ["mp_missing_people.id"]))
    op.create_index("ix_mp_person_photos_person_id", "mp_person_photos", ["person_id"])
    op.create_index("ix_mp_person_photos_verified", "mp_person_photos", ["verified"])

def downgrade() -> None:
    op.drop_table("mp_person_photos")
