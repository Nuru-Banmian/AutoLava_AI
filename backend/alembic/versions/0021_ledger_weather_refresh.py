"""Persist weather work alongside each daily ledger record."""

from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "store_daily_records",
        sa.Column("weather_refresh_due_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "store_daily_records",
        sa.Column(
            "weather_refresh_finished", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index(
        "ix_store_daily_records_weather_refresh_due_at",
        "store_daily_records",
        ["weather_refresh_due_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_store_daily_records_weather_refresh_due_at",
        table_name="store_daily_records",
    )
    op.drop_column("store_daily_records", "weather_refresh_due_at")
    op.drop_column("store_daily_records", "weather_refresh_finished")
