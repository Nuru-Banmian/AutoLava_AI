"""Durable vector synchronization and collection switching."""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_memory_scopes", sa.Column("retrieval_error", sa.String(40), nullable=True))
    op.add_column("agent_memory_index", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_memory_index", sa.Column("error_code", sa.String(40), nullable=True))
    op.add_column("agent_memory_index", sa.Column("fingerprint", sa.String(64), nullable=False, server_default=""))
    op.create_table("agent_index_configuration",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("target", sa.String(64), nullable=False),
                    sa.Column("active", sa.String(64), nullable=False))


def downgrade():
    op.drop_column("agent_memory_scopes", "retrieval_error")
    op.drop_table("agent_index_configuration")
    for column in ("fingerprint", "error_code", "attempts"):
        op.drop_column("agent_memory_index", column)
