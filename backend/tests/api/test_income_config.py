import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import StoreMember, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.services.ledger import LedgerService


@pytest.fixture
async def admin_client(client, user_factory) -> AsyncClient:
    await user_factory(username="config-admin", password="secret", role="admin")
    response = await client.post(
        "/api/auth/login",
        json={"username": "config-admin", "password": "secret"},
    )
    assert response.status_code == 200
    return client


async def test_current_config_has_only_current_categories(
    auth_client, admin_client, store_factory, db_session: AsyncSession
) -> None:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    store = await store_factory(name="User current config")
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.flush()

    configured = await admin_client.put(
        f"/api/admin/stores/{store.id}/income-config",
        json={
            "enabled": True,
            "items": [
                {"name": "现金", "include_in_total": True},
                {
                    "name": "代收款",
                    "include_in_total": False,
                    "sort_order": 1,
                },
            ],
        },
    )
    assert configured.status_code == 200
    cash, agency = list(
        await db_session.scalars(
            select(IncomeCategory)
            .where(IncomeCategory.store_id == store.id)
            .order_by(IncomeCategory.sort_order)
        )
    )

    current = await auth_client.get(f"/api/income-config/{store.id}/current")
    assert current.status_code == 200
    assert current.json() == {
        "store_id": store.id,
        "enabled": True,
        "formula": "营业额 = 现金；“代收款”只记录，不计入营业额",
        "items": [
            {
                "id": cash.id,
                "store_id": store.id,
                "name": "现金",
                "include_in_total": True,
                "is_active": True,
                "sort_order": 0,
                "archived_at": None,
            },
            {
                "id": agency.id,
                "store_id": store.id,
                "name": "代收款",
                "include_in_total": False,
                "is_active": True,
                "sort_order": 1,
                "archived_at": None,
            },
        ],
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/admin/stores/1/income-config/versions"),
        ("post", "/api/admin/stores/1/income-config/versions/1/restore"),
    ],
)
async def test_income_config_version_routes_do_not_exist(
    admin_client, method: str, path: str
) -> None:
    assert (await admin_client.request(method, path)).status_code == 404


async def test_used_category_can_be_archived_but_not_permanently_deleted(
    admin_client, store_factory, user_factory, db_session: AsyncSession
) -> None:
    owner = await user_factory(username="category-owner", password="secret")
    store = await store_factory(name="Protected category")
    category = IncomeCategory(
        store_id=store.id, name="Used", include_in_total=True, is_active=True, sort_order=0
    )
    db_session.add(category)
    await db_session.flush()
    record = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 1),
        daily_revenue=1,
        income_mode="composed",
        wash_count=1,
        is_open="营业",
        weather=None,
        weather_auto=None,
        weather_code=None,
        temperature_max=None,
        temperature_min=None,
        precipitation=None,
        activity=None,
        weather_edited=False,
        scanned=False,
        created_by=owner.id,
        updated_by=owner.id,
    )
    db_session.add(record)
    await db_session.flush()
    db_session.add(
        DailyIncomeItem(
            record_id=record.id,
            category_id=category.id,
            category_name=category.name,
            include_in_total=True,
            sort_order=0,
            amount=1,
        )
    )
    await db_session.flush()

    rejected = await admin_client.delete(f"/api/admin/income-categories/{category.id}")
    archived = await admin_client.post(f"/api/admin/income-categories/{category.id}/archive")

    assert rejected.status_code == 409
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None


async def test_current_category_patch_preserves_historical_total_and_item_snapshot(
    admin_client, store_factory, user_factory, db_session: AsyncSession
) -> None:
    owner = await user_factory(username="snapshot-owner", password="secret")
    store = await store_factory(name="Historical category snapshot")
    category = IncomeCategory(
        store_id=store.id,
        name="Current name",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add(category)
    await db_session.flush()
    record = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 1),
        daily_revenue=150,
        income_mode="composed",
        wash_count=1,
        is_open="营业",
        weather_edited=False,
        created_by=owner.id,
        updated_by=owner.id,
    )
    db_session.add(record)
    await db_session.flush()
    item = DailyIncomeItem(
        record_id=record.id,
        category_id=category.id,
        category_name="Historical name",
        include_in_total=True,
        sort_order=0,
        amount=150,
    )
    db_session.add(item)
    await db_session.flush()

    response = await admin_client.patch(
        f"/api/admin/income-categories/{category.id}",
        json={
            "name": "Renamed current category",
            "include_in_total": False,
            "sort_order": 9,
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed current category"
    assert response.json()["include_in_total"] is False
    assert response.json()["sort_order"] == 9
    await db_session.refresh(record)
    await db_session.refresh(item)
    assert record.daily_revenue == 150
    assert (
        item.category_name,
        item.include_in_total,
        item.sort_order,
        item.amount,
    ) == ("Historical name", True, 0, 150)


async def test_admin_category_commit_waits_for_shared_sqlite_write_lock(
    admin_client,
    store_factory,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await store_factory(name="Category lock")
    category = IncomeCategory(
        store_id=store.id,
        name="Before",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add(category)
    await db_session.flush()
    ledger_entered = asyncio.Event()
    release_ledger = asyncio.Event()
    target = datetime.now(ZoneInfo(store.timezone)).date()

    async def hold_ledger(*_args, **_kwargs):
        ledger_entered.set()
        await release_ledger.wait()
        return True, 789, target

    async def canonical_record(*_args, **_kwargs):
        return SimpleNamespace(id=789, date=target)

    monkeypatch.setattr(LedgerService, "_upsert_locked", hold_ledger)
    monkeypatch.setattr(LedgerService, "_find_record", canonical_record)
    ledger_task = asyncio.create_task(
        LedgerService(SimpleNamespace(rollback=None)).upsert(
            store=store,
            record_date=target,
            payload={},
            actor=SimpleNamespace(id=88),
        )
    )
    await ledger_entered.wait()
    patch_task = asyncio.create_task(
        admin_client.patch(
            f"/api/admin/income-categories/{category.id}",
            json={"name": "After"},
        )
    )
    await asyncio.sleep(0.05)
    was_blocked = not patch_task.done()
    release_ledger.set()
    _, response = await asyncio.gather(ledger_task, patch_task)
    assert response.status_code == 200
    assert was_blocked is True
