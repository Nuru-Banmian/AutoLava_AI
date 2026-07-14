"""add explicit audit rollbackability

Revision ID: 7a8b9c0d1e2f
Revises: 6f7c8d9e0a1b
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "7a8b9c0d1e2f"
down_revision: str | None = "6f7c8d9e0a1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column("rollbackable", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("audit_log", "rollbackable")
