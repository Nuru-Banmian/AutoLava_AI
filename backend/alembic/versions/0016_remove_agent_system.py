"""retire the previous Agent schema without deleting its data"""

from collections.abc import Sequence

from alembic import op


revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
PREVIOUS_AGENT_TABLES = (
    "agent_investigation_cards",
    "agent_turns",
    "agent_messages",
    "agent_conversations",
    "agent_system_settings",
)


def upgrade() -> None:
    for table in PREVIOUS_AGENT_TABLES:
        op.rename_table(table, f"retired_{table}")


def downgrade() -> None:
    for table in reversed(PREVIOUS_AGENT_TABLES):
        op.rename_table(f"retired_{table}", table)
