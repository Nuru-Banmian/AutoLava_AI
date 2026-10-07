"""Fence conversation work and persist request identities."""

from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_conversations", sa.Column("generation", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_runs", sa.Column("generation", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_runs", sa.Column("request_id", sa.String(80), nullable=True))
    op.add_column("agent_runs", sa.Column("input", sa.Text(), nullable=False, server_default=""))
    op.create_index("uq_agent_run_request", "agent_runs", ["conversation_id", "request_id"], unique=True)


def downgrade():
    op.drop_index("uq_agent_run_request", table_name="agent_runs")
    for column in ("input", "request_id", "generation"):
        op.drop_column("agent_runs", column)
    op.drop_column("agent_conversations", "generation")
