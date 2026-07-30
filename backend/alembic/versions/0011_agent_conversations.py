"""add clean-sheet Agent conversations and messages"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_reused_legacy_revision() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "agent_system_settings" in tables:
        return

    for table in (
        "agent_evidence",
        "agent_messages",
        "agent_conversations",
        "agent_alerts",
        "agent_run_stats",
        "agent_settings",
    ):
        if table in tables:
            op.drop_table(table)

    op.create_table(
        "agent_system_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
        sa.CheckConstraint(
            "id = 1",
            name=op.f("ck_agent_system_settings_singleton"),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_agent_system_settings"),
        ),
    )


def upgrade() -> None:
    _replace_reused_legacy_revision()
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("context_summary", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "store_id",
            name="uq_agent_conversations_user_store",
        ),
    )
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.CheckConstraint(
            "role in ('user','assistant')",
            name=op.f("ck_agent_messages_role"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("agent_messages")
    op.drop_table("agent_conversations")
