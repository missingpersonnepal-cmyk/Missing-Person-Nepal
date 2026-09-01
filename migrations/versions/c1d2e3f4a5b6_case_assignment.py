"""add case staff assignment fields"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("mp_missing_people", sa.Column("assigned_admin_id", sa.Integer(), nullable=True))
    op.add_column("mp_missing_people", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_mp_people_assigned_admin", "mp_missing_people", "mp_admins", ["assigned_admin_id"], ["id"])
    op.create_index("ix_mp_missing_people_assigned_admin_id", "mp_missing_people", ["assigned_admin_id"])

def downgrade() -> None:
    op.drop_index("ix_mp_missing_people_assigned_admin_id", table_name="mp_missing_people")
    op.drop_constraint("fk_mp_people_assigned_admin", "mp_missing_people", type_="foreignkey")
    op.drop_column("mp_missing_people", "assigned_at")
    op.drop_column("mp_missing_people", "assigned_admin_id")
