"""Message-associated immutable chart snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_charts",
        sa.Column("chart_id", sa.String(32), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("agent_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("message_id", "position", name="uq_agent_chart_position"),
        sa.CheckConstraint("position >= 0 AND position < 8", name="agent_chart_position"),
        sa.CheckConstraint("byte_size > 0 AND byte_size <= 98304", name="agent_chart_size"),
        sa.CheckConstraint("schema_version = 1", name="agent_chart_schema"),
    )
    op.create_index("ix_agent_charts_message_id", "agent_charts", ["message_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM agent_charts")).scalar():
        raise RuntimeError("Cannot downgrade while saved chart snapshots exist")
    op.drop_table("agent_charts")
