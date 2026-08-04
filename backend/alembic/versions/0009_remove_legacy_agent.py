"""remove the legacy Agent schema and all legacy Agent data"""

from collections.abc import Sequence

from alembic import op


revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("agent_evidence")
    op.drop_table("agent_messages")
    op.drop_table("agent_conversations")
    op.drop_table("agent_alerts")
    op.drop_table("agent_run_stats")
    op.drop_table("agent_settings")


def downgrade() -> None:
    raise RuntimeError("legacy Agent data removal is intentionally irreversible")
