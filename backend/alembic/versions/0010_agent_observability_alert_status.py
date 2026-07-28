"""add Agent run identifiers and actionable alert status"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_run_stats",
        sa.Column("run_id", sa.String(length=36), nullable=True),
    )
    op.execute("UPDATE agent_run_stats SET run_id = 'legacy-' || id")
    with op.batch_alter_table("agent_run_stats") as batch_op:
        batch_op.alter_column("run_id", existing_type=sa.String(length=36), nullable=False)
        batch_op.create_index("ix_agent_run_stats_run_id", ["run_id"], unique=False)

    op.add_column(
        "agent_alerts",
        sa.Column("occurrence_count", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "agent_alerts",
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
    )
    op.execute("UPDATE agent_alerts SET last_seen_at = created_at")
    with op.batch_alter_table("agent_alerts") as batch_op:
        batch_op.alter_column("last_seen_at", existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("agent_alerts") as batch_op:
        batch_op.drop_column("last_seen_at")
        batch_op.drop_column("occurrence_count")
    with op.batch_alter_table("agent_run_stats") as batch_op:
        batch_op.drop_index("ix_agent_run_stats_run_id")
        batch_op.drop_column("run_id")
