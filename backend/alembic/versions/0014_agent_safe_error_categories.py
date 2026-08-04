"""add safe Agent investigation error categories"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_investigation_cards",
        sa.Column("error_category", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_investigation_cards", "error_category")
