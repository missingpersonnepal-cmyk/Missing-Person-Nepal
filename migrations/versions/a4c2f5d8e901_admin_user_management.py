"""admin user management fields

Revision ID: a4c2f5d8e901
Revises: f31b6c4d9201
Create Date: 2026-08-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a4c2f5d8e901"
down_revision: Union[str, None] = "f31b6c4d9201"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mp_admins", sa.Column("display_name", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("mp_admins", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("mp_admins", sa.Column("role", sa.String(length=30), nullable=False, server_default="super_admin"))
    op.add_column("mp_admins", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("mp_admins", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_mp_admins_role", "mp_admins", ["role"])


def downgrade() -> None:
    op.drop_index("ix_mp_admins_role", table_name="mp_admins")
    op.drop_column("mp_admins", "must_change_password")
    op.drop_column("mp_admins", "last_login_at")
    op.drop_column("mp_admins", "role")
    op.drop_column("mp_admins", "email")
    op.drop_column("mp_admins", "display_name")
