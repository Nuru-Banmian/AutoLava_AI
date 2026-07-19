from sqlalchemy.dialects import sqlite

from app.models.base import Base
import app.models.identity  # noqa: F401
import app.models.ledger  # noqa: F401
import app.models.operations  # noqa: F401


def test_final_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "stores",
        "store_members",
        "income_categories",
        "store_daily_records",
        "daily_income_items",
        "daily_briefings",
        "scheduled_task_logs",
        "system_alerts",
    }


def test_business_unique_constraints_exist() -> None:
    assert {c.name for c in Base.metadata.tables["store_members"].constraints} >= {
        "uq_store_members_store_user"
    }
    assert {c.name for c in Base.metadata.tables["store_daily_records"].constraints} >= {
        "uq_store_daily_records_store_date"
    }


def test_final_schema_columns_and_money_types() -> None:
    users = Base.metadata.tables["users"].c
    assert "remember_token" not in users

    stores = Base.metadata.tables["stores"].c
    assert "income_items_enabled" in stores

    records = Base.metadata.tables["store_daily_records"].c
    assert "income_config_version_id" not in records
    assert "row_version" not in records
    assert records.daily_revenue.type.compile(dialect=sqlite.dialect()) == "INTEGER"

    items = Base.metadata.tables["daily_income_items"].c
    assert items.amount.type.compile(dialect=sqlite.dialect()) == "INTEGER"
    assert {"category_name", "include_in_total", "sort_order"} <= set(items.keys())
