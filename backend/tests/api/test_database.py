from datetime import date
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.models.identity import StoreMember, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/database/1/history"),
        ("post", "/api/database/1/history/1/rollback"),
        ("post", "/api/database/1/rollback/1"),
    ],
)
async def test_history_and_rollback_routes_do_not_exist(
    auth_client, method: str, path: str
) -> None:
    response = await auth_client.request(method, path)
    assert response.status_code == 404


async def test_database_records_route_remains_available_for_assigned_user(
    auth_client, store_factory, db_session
) -> None:
    store = await store_factory(name="Records")
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.flush()

    response = await auth_client.get(f"/api/database/{store.id}/records")

    assert response.status_code == 200


async def test_database_summary_and_export_use_integer_money(
    auth_client, store_factory, db_session
) -> None:
    store = await store_factory(name="Integer Records")
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    category = IncomeCategory(
        store_id=store.id,
        name="Cash",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add_all([StoreMember(store_id=store.id, user_id=user.id), category])
    await db_session.flush()
    record = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 18),
        daily_revenue=321,
        income_mode="composed",
        is_open="营业",
        weather_edited=False,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(record)
    await db_session.flush()
    db_session.add(
        DailyIncomeItem(
            record_id=record.id,
            category_id=category.id,
            category_name="Cash",
            include_in_total=True,
            sort_order=0,
            amount=321,
        )
    )
    await db_session.flush()

    page = await auth_client.get(f"/api/database/{store.id}/records")
    exported = await auth_client.get(f"/api/database/{store.id}/export.xlsx")

    assert page.status_code == exported.status_code == 200
    assert page.json()["sum_daily_revenue"] == 321
    assert isinstance(page.json()["sum_daily_revenue"], int)
    workbook = load_workbook(BytesIO(exported.content), read_only=False)
    sheet = workbook["经营记录"]
    assert sheet.cell(row=2, column=3).value == 321
    assert sheet.cell(row=2, column=3).number_format == "€#,##0"
    assert sheet.cell(row=2, column=4).value == 321
    assert sheet.cell(row=2, column=4).number_format == "€#,##0"
