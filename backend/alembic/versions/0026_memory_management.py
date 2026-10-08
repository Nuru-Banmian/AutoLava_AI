"""Memory tombstones, scoped submission guards and independent correction evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_memories", sa.Column("deleted", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("agent_memory_index", sa.Column("operation", sa.String(16), nullable=False, server_default="upsert"))
    op.add_column("agent_runs", sa.Column("memory_revision", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "agent_memory_scopes",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "agent_memory_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("memory_id", sa.String(32), sa.ForeignKey("agent_memories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("previous_content", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_memory_changes_memory_id", "agent_memory_changes", ["memory_id"])


def downgrade():
    op.drop_table("agent_memory_changes")
    op.drop_table("agent_memory_scopes")
    op.drop_column("agent_runs", "memory_revision")
    op.drop_column("agent_memory_index", "operation")
    op.drop_column("agent_memories", "deleted")
