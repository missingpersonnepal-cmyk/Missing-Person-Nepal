"""allow standalone SOS alerts without a disaster event"""
from typing import Sequence, Union
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.alter_column("mp_submissions", "disaster_id", nullable=True)

def downgrade() -> None:
    op.alter_column("mp_submissions", "disaster_id", nullable=False)
