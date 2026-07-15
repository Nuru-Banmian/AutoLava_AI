from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import StoreMember, User
from app.models.income_config import IncomeConfigVersion, IncomeConfigVersionItem
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord


@pytest.fixture
async def admin_client(client, user_factory) -> AsyncClient:
    await user_factory(username="config-admin", password="secret", role="admin")
    response = await client.post(
        "/api/auth/login",
        json={"username": "config-admin", "password": "secret", "remember": False},
    )
    assert response.status_code == 200
    return client


async def test_assigned_user_reads_empty_and_published_current_config(
    auth_client, store_factory, db_session: AsyncSession
) -> None:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    store = await store_factory(name="User current config")
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.flush()

    empty = await auth_client.get(f"/api/income-config/{store.id}/current")
    assert empty.status_code == 200
    assert empty.json() == {
        "store_id": store.id,
        "version_id": None,
        "version": 0,
        "enabled": False,
        "formula": "总收入 = €0.00",
        "created_at": None,
        "items": [],
    }

    version = IncomeConfigVersion(
        store_id=store.id,
        version=1,
        enabled=True,
        created_by=user.id,
        items=[
            IncomeConfigVersionItem(
                category_id=None,
                name="现金",
                include_in_total=True,
                is_active=True,
                sort_order=0,
            )
        ],
    )
    db_session.add(version)
    await db_session.flush()

    configured = await auth_client.get(f"/api/income-config/{store.id}/current")
    assert configured.status_code == 200
    payload = configured.json()
    assert payload["store_id"] == store.id
    assert payload["version_id"] == version.id
    assert payload["version"] == 1
    assert payload["enabled"] is True
    assert payload["formula"] == "总收入 = 现金"
    assert payload["items"] == [
        {
            "id": version.items[0].id,
            "category_id": None,
            "name": "现金",
            "include_in_total": True,
            "is_active": True,
            "sort_order": 0,
        }
    ]


async def test_admin_reads_current_config_for_existing_store(
    admin_client, store_factory
) -> None:
    store = await store_factory(name="Admin current config")

    response = await admin_client.get(f"/api/income-config/{store.id}/current")

    assert response.status_code == 200
    assert response.json()["store_id"] == store.id
    assert response.json()["enabled"] is False


async def test_current_config_hides_unassigned_and_missing_stores(
    auth_client, store_factory
) -> None:
    unassigned = await store_factory(name="Hidden current config")

    hidden = await auth_client.get(f"/api/income-config/{unassigned.id}/current")
    missing = await auth_client.get("/api/income-config/999999/current")

    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json() == {"detail": "Store not found"}

    versions = await auth_client.get(
        f"/api/admin/stores/{unassigned.id}/income-config/versions"
    )
    update = await auth_client.put(
        f"/api/admin/stores/{unassigned.id}/income-config",
        json={"enabled": False, "items": []},
    )
    assert versions.status_code == update.status_code == 403


async def test_publish_selects_exact_items_for_total(
    admin_client, store_factory, db_session: AsyncSession
) -> None:
    store = await store_factory(name="Configured")
    response = await admin_client.put(
        f"/api/admin/stores/{store.id}/income-config",
        json={
            "enabled": True,
            "items": [
                {
                    "category_id": None,
                    "name": "现金",
                    "include_in_total": True,
                    "is_active": True,
                    "sort_order": 1,
                },
                {
                    "category_id": None,
                    "name": "外卖平台",
                    "include_in_total": False,
                    "is_active": True,
                    "sort_order": 2,
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 1
    assert payload["enabled"] is True
    assert payload["formula"] == "总收入 = 现金"
    assert [item["name"] for item in payload["items"]] == ["现金", "外卖平台"]
    assert len((await db_session.scalars(select(IncomeCategory))).all()) == 2


async def test_publish_is_immutable_and_restore_creates_latest_version(
    admin_client, store_factory, db_session: AsyncSession
) -> None:
    store = await store_factory(name="Version history")
    first = await admin_client.put(
        f"/api/admin/stores/{store.id}/income-config",
        json={
            "enabled": True,
            "items": [
                {
                    "category_id": None,
                    "name": "现金",
                    "include_in_total": True,
                    "is_active": True,
                    "sort_order": 0,
                }
            ],
        },
    )
    category_id = first.json()["items"][0]["category_id"]
    second = await admin_client.put(
        f"/api/admin/stores/{store.id}/income-config",
        json={
            "enabled": True,
            "items": [
                {
                    "category_id": category_id,
                    "name": "现金收款",
                    "include_in_total": False,
                    "is_active": True,
                    "sort_order": 0,
                }
            ],
        },
    )
    assert second.status_code == 200
    versions = await admin_client.get(
        f"/api/admin/stores/{store.id}/income-config/versions"
    )
    assert [item["version"] for item in versions.json()] == [2, 1]
    assert versions.json()[1]["items"][0]["name"] == "现金"

    restored = await admin_client.post(
        f"/api/admin/stores/{store.id}/income-config/versions/{first.json()['version_id']}/restore"
    )
    assert restored.status_code == 200
    assert restored.json()["version"] == 3
    assert restored.json()["items"][0]["name"] == "现金"
    rows = (
        await db_session.scalars(
            select(IncomeConfigVersionItem).order_by(IncomeConfigVersionItem.id)
        )
    ).all()
    assert [row.name for row in rows] == ["现金", "现金收款", "现金"]


async def test_used_category_can_be_archived_and_restored_but_not_deleted(
    admin_client, store_factory, user_factory, db_session: AsyncSession
) -> None:
    owner = await user_factory(username="config-owner", password="secret")
    store = await store_factory(name="Archive")
    category = IncomeCategory(
        store_id=store.id,
        name="Used",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add(category)
    await db_session.flush()
    record = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 13),
        daily_revenue=Decimal("25.00"),
        wash_count=3,
        is_open="营业",
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
            amount=Decimal("25.00"),
        )
    )
    await db_session.flush()

    archived = await admin_client.post(
        f"/api/admin/income-categories/{category.id}/archive"
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert (
        await admin_client.delete(f"/api/admin/income-categories/{category.id}")
    ).status_code == 409
    restored = await admin_client.post(
        f"/api/admin/income-categories/{category.id}/restore"
    )
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    assert restored.json()["is_active"] is False


async def test_publish_rejects_duplicate_names_and_foreign_store_category(
    admin_client, store_factory, db_session: AsyncSession
) -> None:
    store = await store_factory(name="Target")
    other = await store_factory(name="Other")
    foreign = IncomeCategory(
        store_id=other.id,
        name="Foreign",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add(foreign)
    await db_session.flush()

    duplicate = await admin_client.put(
        f"/api/admin/stores/{store.id}/income-config",
        json={
            "enabled": True,
            "items": [
                {"name": "Cash", "include_in_total": True},
                {"name": "cash", "include_in_total": False},
            ],
        },
    )
    assert duplicate.status_code == 422
    foreign_response = await admin_client.put(
        f"/api/admin/stores/{store.id}/income-config",
        json={
            "enabled": True,
            "items": [
                {
                    "category_id": foreign.id,
                    "name": foreign.name,
                    "include_in_total": True,
                }
            ],
        },
    )
    assert foreign_response.status_code == 422
    assert (await db_session.scalars(select(IncomeConfigVersion))).all() == []


async def test_delete_unused_keeps_version_snapshot_and_restore_recreates_category(
    admin_client, store_factory, db_session: AsyncSession
) -> None:
    store = await store_factory(name="Deleted snapshot")
    published = await admin_client.put(
        f"/api/admin/stores/{store.id}/income-config",
        json={
            "enabled": True,
            "items": [
                {
                    "name": "Mistake",
                    "include_in_total": True,
                    "is_active": True,
                    "sort_order": 3,
                }
            ],
        },
    )
    source = published.json()
    store_id = store.id
    old_category_id = source["items"][0]["category_id"]

    deleted = await admin_client.delete(
        f"/api/admin/income-categories/{old_category_id}"
    )
    assert deleted.status_code == 204
    db_session.expire_all()
    snapshot = await db_session.get(IncomeConfigVersionItem, source["items"][0]["id"])
    assert snapshot is not None
    assert snapshot.category_id is None
    assert snapshot.name == "Mistake"
    current = await admin_client.get(
        f"/api/admin/stores/{store_id}/income-config"
    )
    assert current.status_code == 200
    assert current.json()["items"] == []

    restored = await admin_client.post(
        f"/api/admin/stores/{store_id}/income-config/versions/{source['version_id']}/restore"
    )
    assert restored.status_code == 200
    restored_item = restored.json()["items"][0]
    assert restored_item["name"] == "Mistake"
    assert restored_item["category_id"] != old_category_id
