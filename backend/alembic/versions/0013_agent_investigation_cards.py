"""add Agent investigation cards"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_investigation_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=120), nullable=False),
        sa.Column("range_start", sa.String(length=10), nullable=True),
        sa.Column("range_end", sa.String(length=10), nullable=True),
        sa.Column(
            "filters_json",
            sa.Text(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('completed','empty','unavailable','failed')",
            name=op.f("ck_agent_investigation_cards_status"),
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"],
            ["agent_turns.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_investigation_cards_turn_id"),
        "agent_investigation_cards",
        ["turn_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_agent_investigation_cards_turn_id"),
        table_name="agent_investigation_cards",
    )
    op.drop_table("agent_investigation_cards")
