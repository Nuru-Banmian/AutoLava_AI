from sqlalchemy.dialects import sqlite

from app.models.base import Base
import app.models.identity  # noqa: F401
import app.models.ledger  # noqa: F401
import app.models.operations  # noqa: F401
import app.models.settlement  # noqa: F401


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
        "settlement_companies",
        "settlement_records",
        "settlement_audit_events",
    }


def test_business_unique_constraints_exist() -> None:
    assert {c.name for c in Base.metadata.tables["store_members"].constraints} >= {
        "uq_store_members_store_user"
    }
    assert {c.name for c in Base.metadata.tables["store_daily_records"].constraints} >= {
        "uq_store_daily_records_store_date"
    }
    company_indexes = {
        index.name: index for index in Base.metadata.tables["settlement_companies"].indexes
    }
    active_names = company_indexes["uq_settlement_companies_active_store_name"]
    assert active_names.unique is True
    assert {column.name for column in active_names.columns} == {"store_id", "normalized_name"}
    assert active_names.dialect_options["sqlite"]["where"] is not None


def test_final_schema_columns_and_money_types() -> None:
    users = Base.metadata.tables["users"].c
    assert "remember_token" not in users

    stores = Base.metadata.tables["stores"].c
    assert "income_items_enabled" in stores
    assert "company_settlement_enabled" in stores

    records = Base.metadata.tables["store_daily_records"].c
    assert "income_config_version_id" not in records
    assert "row_version" not in records
    assert records.daily_revenue.type.compile(dialect=sqlite.dialect()) == "INTEGER"

    items = Base.metadata.tables["daily_income_items"].c
    assert items.amount.type.compile(dialect=sqlite.dialect()) == "INTEGER"
    assert {"category_name", "include_in_total", "sort_order"} <= set(items.keys())
