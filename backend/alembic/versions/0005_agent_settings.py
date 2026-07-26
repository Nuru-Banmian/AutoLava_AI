"""add the persistent global Agent switch"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default="0", nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_settings")),
    )


def downgrade() -> None:
    op.drop_table("agent_settings")
