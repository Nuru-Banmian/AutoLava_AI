"""add validated actions to agent messages

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_messages") as batch_op:
        batch_op.add_column(sa.Column("action", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_messages") as batch_op:
        batch_op.drop_column("action")
