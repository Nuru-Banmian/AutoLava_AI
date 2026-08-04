"""add the clean-sheet Agent system setting"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_system_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_agent_system_settings_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_system_settings")),
    )


def downgrade() -> None:
    op.drop_table("agent_system_settings")
