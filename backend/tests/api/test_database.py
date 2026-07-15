from dataclasses import dataclass
from datetime import date
from io import BytesIO

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.database import router as database_router
from app.models.audit import AuditLog
from app.models.identity import Store, StoreMember, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.services.audit import record_snapshot
from app.services.ledger import LedgerService


@dataclass
class DatabaseContext:
    store: Store
    user: User
    editor: User
    cash: IncomeCategory
    card: IncomeCategory
    legacy: IncomeCategory
    records: list[StoreDailyRecord]

    @property
    def id(self) -> int:
        return self.store.id


async def grant_authenticated_admin(db_session: AsyncSession) -> User:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    user.role = "admin"
    await db_session.flush()
    return user


def test_database_router_uses_canonical_record_and_rollback_paths() -> None:
    route_contracts = {
        (method, route.path) for route in database_router.routes for method in route.methods
    }

    assert ("GET", "/database/{store_id}/records") in route_contracts
    assert (
        "POST",
        "/database/{store_id}/history/{audit_id}/rollback",
    ) in route_contracts
    assert ("GET", "/database/{store_id}") not in route_contracts
    assert ("POST", "/database/{store_id}/rollback/{audit_id}") not in route_contracts


@pytest.fixture
async def database_context(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    store_factory,
    user_factory,
) -> DatabaseContext:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    editor = await user_factory(username="database-editor", password="secret")
    store = await store_factory(name="Database Store", timezone="Europe/Berlin")
    cash = IncomeCategory(
        store_id=store.id,
        name="现金",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    card = IncomeCategory(
        store_id=store.id,
        name="刷卡",
        include_in_total=True,
        is_active=True,
        sort_order=1,
    )
    legacy = IncomeCategory(
        store_id=store.id,
        name="历史收入",
        include_in_total=True,
        is_active=False,
        sort_order=2,
    )
    db_session.add_all([StoreMember(store_id=store.id, user_id=user.id), cash, card, legacy])
    await db_session.flush()

    records = [
        StoreDailyRecord(
            store_id=store.id,
            date=date(2026, 7, 1),
            daily_revenue="100.10",
            wash_count=5,
            is_open="营业",
            weather="晴",
            activity="VIP Alpha 优惠",
            weather_edited=True,
            scanned=False,
            created_by=user.id,
            updated_by=editor.id,
            items=[
                DailyIncomeItem(category_id=cash.id, amount="60.10"),
                DailyIncomeItem(category_id=card.id, amount="39.99"),
                DailyIncomeItem(category_id=legacy.id, amount="0.01"),
            ],
        ),
        StoreDailyRecord(
            store_id=store.id,
            date=date(2026, 7, 2),
            daily_revenue="0.00",
            wash_count=0,
            is_open="休息",
            weather="多云",
            activity=None,
            weather_edited=False,
            scanned=False,
            created_by=user.id,
            updated_by=user.id,
            items=[
                DailyIncomeItem(category_id=cash.id, amount="0.00"),
                DailyIncomeItem(category_id=card.id, amount="0.00"),
            ],
        ),
        StoreDailyRecord(
            store_id=store.id,
            date=date(2026, 7, 3),
            daily_revenue="45.25",
            wash_count=None,
            is_open="天气停业",
            weather="雨",
            activity="alpha 特价",
            weather_edited=False,
            scanned=True,
            created_by=editor.id,
            updated_by=editor.id,
            items=[
                DailyIncomeItem(category_id=cash.id, amount="25.00"),
                DailyIncomeItem(category_id=card.id, amount="20.25"),
            ],
        ),
    ]
    db_session.add_all(records)
    await db_session.flush()
    return DatabaseContext(
        store=store,
        user=user,
        editor=editor,
        cash=cash,
        card=card,
        legacy=legacy,
        records=records,
    )


async def test_record_page_is_deterministic_and_sum_uses_all_filtered_rows(
    auth_client: AsyncClient, database_context: DatabaseContext
) -> None:
    response = await auth_client.get(
        f"/api/database/{database_context.id}/records",
        params={"page": 1, "page_size": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] == 3
    assert body["sum_daily_revenue"] == "145.35"
    assert [item["date"] for item in body["items"]] == ["2026-07-03", "2026-07-02"]
    assert body["items"][0]["created_by_name"] == "database-editor"

    second_page = await auth_client.get(
        f"/api/database/{database_context.id}/records",
        params={"page": 2, "page_size": 2},
    )
    assert [item["date"] for item in second_page.json()["items"]] == ["2026-07-01"]
    assert [category["name"] for category in second_page.json()["categories"]] == [
        "现金",
        "刷卡",
        "历史收入",
    ]


@pytest.mark.parametrize(
    ("params", "dates", "expected_sum"),
    [
        ({"start": "2026-07-01", "end": "2026-07-02"}, ["2026-07-02", "2026-07-01"], "100.10"),
        ({"status": "营业"}, ["2026-07-01"], "100.10"),
        ({"weather": "雨"}, ["2026-07-03"], "45.25"),
        ({"activity_query": "ALPHA"}, ["2026-07-03", "2026-07-01"], "145.35"),
        ({"missing_wash_count": "true"}, ["2026-07-03"], "45.25"),
    ],
)
async def test_record_filters_are_inclusive_and_feed_the_interval_sum(
    auth_client: AsyncClient,
    database_context: DatabaseContext,
    params: dict[str, str],
    dates: list[str],
    expected_sum: str,
) -> None:
    response = await auth_client.get(f"/api/database/{database_context.id}/records", params=params)

    assert response.status_code == 200
    assert [item["date"] for item in response.json()["items"]] == dates
    assert response.json()["sum_daily_revenue"] == expected_sum


async def test_invalid_filter_interval_is_rejected(
    auth_client: AsyncClient, database_context: DatabaseContext
) -> None:
    response = await auth_client.get(
        f"/api/database/{database_context.id}/records",
        params={"start": "2026-07-03", "end": "2026-07-01"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "start must be on or before end"}


async def test_activity_substring_treats_sql_wildcards_as_literal_text(
    auth_client: AsyncClient,
    database_context: DatabaseContext,
    db_session: AsyncSession,
) -> None:
    database_context.records[0].activity = "满 100% 优惠"
    await db_session.flush()

    response = await auth_client.get(
        f"/api/database/{database_context.id}/records",
        params={"activity_query": "%"},
    )

    assert response.status_code == 200
    assert [item["date"] for item in response.json()["items"]] == ["2026-07-01"]


async def test_export_rows_and_dynamic_columns_match_active_filters(
    auth_client: AsyncClient, database_context: DatabaseContext
) -> None:
    params = {"start": "2026-07-01", "end": "2026-07-31", "status": "营业"}
    page = await auth_client.get(f"/api/database/{database_context.id}/records", params=params)
    response = await auth_client.get(
        f"/api/database/{database_context.id}/export.xlsx", params=params
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["content-disposition"] == (
        f'attachment; filename="ledger-{database_context.id}-2026-07-01-2026-07-31.xlsx"'
    )
    rows = list(load_workbook(BytesIO(response.content), data_only=False).active.values)
    assert rows[0] == (
        "日期",
        "状态",
        "总收入",
        "现金",
        "刷卡",
        "历史收入",
        "洗车",
        "天气",
        "活动",
        "记录人",
        "最后修改人",
    )
    assert [row[0].date().isoformat() for row in rows[1:]] == [
        item["date"] for item in page.json()["items"]
    ]
    assert rows[1][1:] == (
        "营业",
        100.1,
        60.1,
        39.99,
        0.01,
        5,
        "晴",
        "VIP Alpha 优惠",
        "authenticated",
        "database-editor",
    )


async def test_empty_export_has_deterministic_active_columns_and_no_data_rows(
    auth_client: AsyncClient, database_context: DatabaseContext
) -> None:
    response = await auth_client.get(
        f"/api/database/{database_context.id}/export.xlsx",
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )

    assert response.status_code == 200
    rows = list(load_workbook(BytesIO(response.content)).active.values)
    assert rows == [
        ("日期", "状态", "总收入", "现金", "刷卡", "洗车", "天气", "活动", "记录人", "最后修改人")
    ]


async def test_export_escapes_formula_style_category_and_text_values(
    auth_client: AsyncClient,
    database_context: DatabaseContext,
    db_session: AsyncSession,
) -> None:
    database_context.legacy.name = "=SUM(A1:A2)"
    database_context.records[0].activity = "+2+2"
    await db_session.flush()

    response = await auth_client.get(
        f"/api/database/{database_context.id}/export.xlsx",
        params={"status": "营业"},
    )

    rows = list(load_workbook(BytesIO(response.content), data_only=False).active.values)
    assert rows[0][5] == "'=SUM(A1:A2)"
    assert rows[1][8] == "'+2+2"


async def test_history_is_ledger_only_store_isolated_and_newest_first(
    auth_client: AsyncClient,
    database_context: DatabaseContext,
    db_session: AsyncSession,
    store_factory,
) -> None:
    await grant_authenticated_admin(db_session)
    first_record = database_context.records[0]
    other_store = await store_factory(name="Other history store")
    db_session.add_all(
        [
            AuditLog(
                operation_domain="ledger",
                store_id=database_context.id,
                record_id=first_record.id,
                record_date=first_record.date,
                operation_type="create",
                operation_source="manual",
                operator_user_id=database_context.user.id,
                before_json=None,
                after_json={"version": 1},
                description="first",
                requires_approval=False,
                approved=True,
            ),
            AuditLog(
                operation_domain="ledger",
                store_id=database_context.id,
                record_id=first_record.id,
                record_date=first_record.date,
                operation_type="update",
                operation_source="manual",
                operator_user_id=database_context.editor.id,
                before_json={"version": 1},
                after_json={"version": 2},
                description="second",
                requires_approval=False,
                approved=True,
            ),
            AuditLog(
                operation_domain="ledger",
                store_id=other_store.id,
                record_id=None,
                record_date=date(2026, 7, 1),
                operation_type="delete",
                operation_source="manual",
                operator_user_id=database_context.user.id,
                before_json={"other": True},
                after_json=None,
                description="other store",
                requires_approval=False,
                approved=True,
            ),
            AuditLog(
                operation_domain="admin",
                store_id=database_context.id,
                record_id=database_context.id,
                record_date=None,
                operation_type="update",
                operation_source="manual",
                operator_user_id=database_context.user.id,
                before_json=None,
                after_json=None,
                description="admin operation",
                requires_approval=False,
                approved=True,
            ),
        ]
    )
    await db_session.flush()

    response = await auth_client.get(f"/api/database/{database_context.id}/history")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["page"] == 1
    assert payload["page_size"] == 20
    assert [entry["description"] for entry in payload["items"]] == ["second", "first"]
    assert payload["items"][0]["operator_username"] == "database-editor"
    assert payload["items"][0]["before"] == {"version": 1}
    assert payload["items"][0]["after"] == {"version": 2}

    second_page = await auth_client.get(
        f"/api/database/{database_context.id}/history",
        params={"page": 2, "page_size": 1, "record_id": first_record.id},
    )
    assert second_page.status_code == 200
    assert [item["description"] for item in second_page.json()["items"]] == ["first"]


async def test_rollback_route_restores_record_and_returns_canonical_snapshot(
    auth_client: AsyncClient,
    database_context: DatabaseContext,
    db_session: AsyncSession,
) -> None:
    await grant_authenticated_admin(db_session)
    record = database_context.records[0]
    record.income_mode = "composed"
    await db_session.flush()
    await db_session.refresh(record, attribute_names=["created_at", "updated_at", "items"])
    expected = record_snapshot(record)
    expected["row_version"] = record.row_version + 2
    await LedgerService(db_session).upsert(
        store=database_context.store,
        record_date=record.date,
        payload={
            "is_open": "营业",
            "wash_count": 99,
            "weather": "雨",
            "weather_edited": True,
            "activity": "changed",
            "config_version_id": None,
            "expected_version": record.row_version,
            "items": [
                {"category_id": database_context.cash.id, "amount": "999.99"},
                {"category_id": database_context.card.id, "amount": "1.00"},
                {"category_id": database_context.legacy.id, "amount": "0.01"},
            ],
        },
        actor=database_context.user,
        overwrite=True,
    )
    audit = await db_session.scalar(
        select(AuditLog)
        .where(AuditLog.operation_domain == "ledger", AuditLog.operation_type == "update")
        .order_by(AuditLog.id.desc())
    )
    assert audit is not None

    response = await auth_client.post(
        f"/api/database/{database_context.id}/history/{audit.id}/rollback"
    )

    assert response.status_code == 200
    assert response.json() == {"audit_id": audit.id, "record": expected}


async def test_rollback_route_checks_path_store_against_audit_store(
    auth_client: AsyncClient,
    database_context: DatabaseContext,
    db_session: AsyncSession,
    store_factory,
) -> None:
    actor = await grant_authenticated_admin(db_session)
    other = await store_factory(name="Other rollback store")
    audit = AuditLog(
        operation_domain="ledger",
        store_id=other.id,
        record_id=None,
        record_date=date(2026, 7, 1),
        operation_type="delete",
        operation_source="manual",
        operator_user_id=database_context.user.id,
        before_json={"store_id": other.id},
        after_json=None,
        description="other store audit",
        requires_approval=False,
        approved=True,
    )
    db_session.add(audit)
    await db_session.flush()

    mismatch = await auth_client.post(
        f"/api/database/{database_context.id}/history/{audit.id}/rollback"
    )
    actor.role = "user"
    await db_session.flush()
    inaccessible = await auth_client.post(f"/api/database/{other.id}/history/{audit.id}/rollback")

    assert mismatch.status_code == 404
    assert mismatch.json() == {"detail": "Audit entry not found"}
    assert inaccessible.status_code == 403
    assert inaccessible.json() == {"detail": "Insufficient permissions"}


@pytest.mark.parametrize("suffix", ["/records", "/history", "/export.xlsx"])
async def test_database_routes_hide_unassigned_store(
    auth_client: AsyncClient, store_factory, suffix: str
) -> None:
    other = await store_factory(name="Invisible database store")

    response = await auth_client.get(f"/api/database/{other.id}{suffix}")

    assert response.status_code == (403 if suffix == "/history" else 404)
    assert response.json() == {
        "detail": "Insufficient permissions" if suffix == "/history" else "Store not found"
    }
