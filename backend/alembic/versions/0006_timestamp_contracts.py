"""mark operational timestamp provenance

Revision ID: a0d1e2f3b4c5
Revises: 9c0d1e2f3a4b
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a0d1e2f3b4c5"
down_revision: str | None = "9c0d1e2f3a4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing wall-clock values may have been written in a server-local timezone.
    # The conservative default marks both columns and dashboard JSON as untrusted.
    for table_name in ("daily_briefings", "scheduled_task_logs", "system_alerts"):
        op.add_column(
            table_name,
            sa.Column(
                "timestamp_contract",
                sa.String(length=24),
                nullable=False,
                server_default="legacy_unknown",
            ),
        )


def downgrade() -> None:
    for table_name in ("system_alerts", "scheduled_task_logs", "daily_briefings"):
        op.drop_column(table_name, "timestamp_contract")
