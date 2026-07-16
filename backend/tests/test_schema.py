from app.models.base import Base
import app.models.audit  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.income_config  # noqa: F401
import app.models.ledger  # noqa: F401
import app.models.operations  # noqa: F401


def test_phase_one_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "stores",
        "store_members",
        "store_settings",
        "income_categories",
        "income_config_versions",
        "income_config_version_items",
        "store_daily_records",
        "daily_income_items",
        "audit_log",
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


def test_rollback_target_is_a_nullable_unique_self_reference() -> None:
    table = Base.metadata.tables["audit_log"]

    assert table.c.rollback_of_audit_id.nullable is True
    assert {constraint.name for constraint in table.constraints} >= {
        "fk_audit_log_rollback_of_audit_id_audit_log",
        "uq_audit_log_rollback_of_audit_id",
    }
    foreign_key = next(
        key for key in table.foreign_keys if key.parent.name == "rollback_of_audit_id"
    )
    assert foreign_key.target_fullname == "audit_log.id"


def test_usability_foundation_columns_are_registered() -> None:
    records = Base.metadata.tables["store_daily_records"].c
    assert {"income_mode", "income_config_version_id", "row_version"} <= set(records.keys())

    items = Base.metadata.tables["daily_income_items"].c
    assert {"category_name", "include_in_total", "sort_order"} <= set(items.keys())

    categories = Base.metadata.tables["income_categories"].c
    assert "archived_at" in categories

    audits = Base.metadata.tables["audit_log"].c
    assert "snapshot_expires_at" in audits


def test_income_config_item_keeps_snapshot_when_category_is_deleted() -> None:
    table = Base.metadata.tables["income_config_version_items"]
    foreign_key = next(key for key in table.foreign_keys if key.parent.name == "category_id")

    assert table.c.category_id.nullable is True
    assert foreign_key.ondelete == "SET NULL"


def test_operational_timestamps_persist_their_source_contract() -> None:
    for table_name in ("daily_briefings", "scheduled_task_logs", "system_alerts"):
        column = Base.metadata.tables[table_name].c.timestamp_contract
        assert column.nullable is False
        assert column.server_default is not None
