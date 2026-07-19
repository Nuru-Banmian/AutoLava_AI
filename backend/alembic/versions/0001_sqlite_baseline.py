"""sqlite baseline"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("income_items_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.CheckConstraint("role in ('admin','user')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "daily_briefings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("card_type", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("timestamp_contract", sa.String(length=24), server_default="legacy_unknown", nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_daily_briefings_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_briefings")),
        sa.UniqueConstraint("store_id", "card_type", name="uq_daily_briefings_store_card"),
    )
    op.create_table(
        "income_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("include_in_total", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_income_categories_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_income_categories")),
    )
    op.create_table(
        "scheduled_task_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=True),
        sa.Column("task_type", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("timestamp_contract", sa.String(length=24), server_default="legacy_unknown", nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_scheduled_task_logs_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_task_logs")),
    )
    op.create_table(
        "store_daily_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("daily_revenue", sa.Integer(), nullable=False),
        sa.Column("income_mode", sa.String(length=20), nullable=False),
        sa.Column("wash_count", sa.Integer(), nullable=True),
        sa.Column("is_open", sa.String(length=20), nullable=False),
        sa.Column("weather", sa.String(length=50), nullable=True),
        sa.Column("weather_auto", sa.String(length=50), nullable=True),
        sa.Column("weather_code", sa.Integer(), nullable=True),
        sa.Column("temperature_max", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("temperature_min", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("precipitation", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("activity", sa.Text(), nullable=True),
        sa.Column("weather_edited", sa.Boolean(), nullable=False),
        sa.Column("scanned", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.CheckConstraint("is_open in ('营业','休息','天气停业')", name=op.f("ck_store_daily_records_open_status")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_store_daily_records_created_by_users")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_store_daily_records_store_id_stores")),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_store_daily_records_updated_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_daily_records")),
        sa.UniqueConstraint("store_id", "date", name="uq_store_daily_records_store_date"),
    )
    op.create_table(
        "store_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_store_members_store_id_stores"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_store_members_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_members")),
        sa.UniqueConstraint("store_id", "user_id", name="uq_store_members_store_user"),
    )
    op.create_table(
        "system_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=True),
        sa.Column("alert_type", sa.String(length=60), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_resolved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("timestamp_contract", sa.String(length=24), server_default="legacy_unknown", nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_system_alerts_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_alerts")),
    )
    op.create_table(
        "daily_income_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("category_name", sa.String(length=100), nullable=False),
        sa.Column("include_in_total", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["income_categories.id"], name=op.f("fk_daily_income_items_category_id_income_categories")),
        sa.ForeignKeyConstraint(["record_id"], ["store_daily_records.id"], name=op.f("fk_daily_income_items_record_id_store_daily_records"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_income_items")),
        sa.UniqueConstraint("record_id", "category_id", name=op.f("uq_daily_income_items_record_id")),
    )
    op.create_index("ix_daily_income_items_record_sort", "daily_income_items", ["record_id", "sort_order"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_daily_income_items_record_sort", table_name="daily_income_items")
    op.drop_table("daily_income_items")
    op.drop_table("system_alerts")
    op.drop_table("store_members")
    op.drop_table("store_daily_records")
    op.drop_table("scheduled_task_logs")
    op.drop_table("income_categories")
    op.drop_table("daily_briefings")
    op.drop_table("users")
    op.drop_table("stores")
