"""Persist one revision for each store's income configuration."""

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("income_config_revision", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("stores", "income_config_revision")
