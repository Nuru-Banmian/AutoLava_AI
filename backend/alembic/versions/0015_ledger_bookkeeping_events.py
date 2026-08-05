"""add persisted ledger bookkeeping events"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ledger_bookkeeping_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action in ('created','updated')",
            name=op.f("ck_ledger_bookkeeping_events_bookkeeping_action"),
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["record_id"], ["store_daily_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ledger_bookkeeping_events_record_id",
        "ledger_bookkeeping_events",
        ["record_id", "id"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO ledger_bookkeeping_events
                (store_id, record_id, actor_id, action, occurred_at)
            SELECT store_id, id, created_by, 'created', created_at
            FROM store_daily_records
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ledger_bookkeeping_events_record_id",
        table_name="ledger_bookkeeping_events",
    )
    op.drop_table("ledger_bookkeeping_events")
