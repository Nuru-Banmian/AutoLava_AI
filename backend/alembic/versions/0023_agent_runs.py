"""Persist bounded chat runs and replayable events without rewriting history."""

from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('running','completed','failed')", name="agent_run_status"),
    )
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    op.create_index("uq_agent_runs_active", "agent_runs", ["conversation_id"], unique=True,
                    sqlite_where=sa.text("status = 'running'"))
    op.create_table(
        "agent_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_agent_events_run_id", "agent_events", ["run_id"])


def downgrade():
    op.drop_table("agent_events")
    op.drop_table("agent_runs")
