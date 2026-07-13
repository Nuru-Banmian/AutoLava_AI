from app.models.base import Base
import app.models.audit  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.ledger  # noqa: F401
import app.models.operations  # noqa: F401


def test_phase_one_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "stores",
        "store_members",
        "store_settings",
        "income_categories",
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
