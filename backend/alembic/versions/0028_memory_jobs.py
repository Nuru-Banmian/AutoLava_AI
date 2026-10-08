"""Durable memory curation and versioned candidate decisions."""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_runs", sa.Column("memory_epoch", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_memory_scopes", sa.Column("epoch", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_memories", sa.Column("target_id", sa.String(32)))
    op.add_column("agent_memories", sa.Column("target_version", sa.Integer()))
    op.add_column("agent_memories", sa.Column("decision", sa.String(16)))
    op.create_table(
        "agent_memory_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("auth_identity", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("memory_revision", sa.Integer(), nullable=False),
        sa.Column("memory_epoch", sa.Integer(), nullable=False),
        sa.Column("description_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("result", sa.JSON()),
        sa.Column("failures", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status in ('pending','running','completed','failed','stale')", name="agent_memory_job_status"),
    )
    op.create_index("ix_agent_memory_jobs_status_id", "agent_memory_jobs", ["status", "id"])
    op.create_index("ix_agent_memory_jobs_scope", "agent_memory_jobs", ["user_id", "store_id", "id"])


def downgrade():
    op.drop_table("agent_memory_jobs")
    for column in ("decision", "target_version", "target_id"):
        op.drop_column("agent_memories", column)
    op.drop_column("agent_memory_scopes", "epoch")
    op.drop_column("agent_runs", "memory_epoch")
