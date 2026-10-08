"""Independent memory evidence and atomic index outbox."""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_runs", sa.Column("user_message_id", sa.Integer(), nullable=True))
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status in ('active','pending_confirmation')", name="agent_memory_status"),
    )
    op.create_index("ix_agent_memories_scope", "agent_memories", ["user_id", "store_id", "id"])
    op.create_table(
        "agent_memory_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("memory_id", sa.String(32), sa.ForeignKey("agent_memories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False, unique=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_memory_sources_memory_id", "agent_memory_sources", ["memory_id"])
    op.create_table(
        "agent_memory_index",
        sa.Column("memory_id", sa.String(32), sa.ForeignKey("agent_memories.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.CheckConstraint("status in ('pending','ready','failed')", name="agent_memory_index_status"),
    )


def downgrade():
    op.drop_table("agent_memory_index")
    op.drop_table("agent_memory_sources")
    op.drop_table("agent_memories")
    op.drop_column("agent_runs", "user_message_id")
