"""add structured dashboard card payloads

Revision ID: 9c0d1e2f3a4b
Revises: 8b9c0d1e2f3a
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "9c0d1e2f3a4b"
down_revision: str | None = "8b9c0d1e2f3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("daily_briefings", sa.Column("payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("daily_briefings", "payload")
