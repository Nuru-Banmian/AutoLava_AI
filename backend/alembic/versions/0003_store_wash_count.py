"""store wash count setting"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column(
            "wash_count_enabled",
            sa.Boolean(),
            server_default="1",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("stores", "wash_count_enabled")
