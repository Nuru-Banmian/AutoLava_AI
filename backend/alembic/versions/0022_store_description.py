"""Add independently versioned store descriptions without rewriting existing data."""

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "stores", sa.Column("description_revision", sa.Integer(), nullable=False, server_default="1")
    )


def downgrade() -> None:
    op.drop_column("stores", "description_revision")
    op.drop_column("stores", "description")
