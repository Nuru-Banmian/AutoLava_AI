"""bind Agent enablement to an approved release report

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_settings") as batch_op:
        batch_op.add_column(
            sa.Column("release_approval_id", sa.String(length=64), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_settings") as batch_op:
        batch_op.drop_column("release_approval_id")
