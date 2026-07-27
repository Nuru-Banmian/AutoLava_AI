import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import StoreMember, User


@pytest.fixture
async def admin_client(client: AsyncClient, user_factory, db_session: AsyncSession) -> AsyncClient:
    await user_factory(username="wash-count-admin", password="secret", role="admin")
    response = await client.post(
        "/api/auth/login",
        json={"username": "wash-count-admin", "password": "secret"},
    )
    assert response.status_code == 200
    await db_session.commit()
    return client


async def test_store_contract_defaults_and_scopes_wash_count_setting(
    admin_client: AsyncClient, store_factory, db_session: AsyncSession
) -> None:
    created = await admin_client.post(
        "/api/admin/stores",
        json={
            "name": "Default enabled",
            "address": "Milan",
            "latitude": "45.0",
            "longitude": "9.0",
            "timezone": "Europe/Rome",
        },
    )
    other = await store_factory(name="Other")
    await db_session.commit()

    assert created.status_code == 201
    assert created.json()["wash_count_enabled"] is True
    changed = await admin_client.patch(
        f"/api/admin/stores/{created.json()['id']}",
        json={"wash_count_enabled": False},
    )

    assert changed.status_code == 200
    assert changed.json()["wash_count_enabled"] is False
    await db_session.refresh(other)
    assert other.wash_count_enabled is True
    by_id = {item["id"]: item for item in (await admin_client.get("/api/admin/stores")).json()}
    assert by_id[created.json()["id"]]["wash_count_enabled"] is False
    assert by_id[other.id]["wash_count_enabled"] is True


async def test_regular_user_cannot_modify_but_can_read_assigned_setting(
    auth_client: AsyncClient, store_factory, db_session: AsyncSession
) -> None:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    store = await store_factory(name="Assigned")
    store.wash_count_enabled = False
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.commit()

    denied = await auth_client.patch(
        f"/api/admin/stores/{store.id}",
        json={"wash_count_enabled": True},
    )
    accessible = await auth_client.get("/api/stores/accessible")

    assert denied.status_code == 403
    assert accessible.json()[0]["wash_count_enabled"] is False


async def test_write_rules_preserve_history_while_setting_is_disabled(
    admin_client: AsyncClient, store_factory, db_session: AsyncSession
) -> None:
    store = await store_factory(name="Write rules")
    await db_session.commit()
    first_path = f"/api/ledger/{store.id}/2026-07-20"
    second_path = f"/api/ledger/{store.id}/2026-07-21"
    body = {
        "is_open": "营业",
        "daily_revenue": 120,
        "wash_count": 7,
        "weather": None,
        "weather_edited": False,
        "activity": None,
        "items": [],
    }

    assert (await admin_client.put(first_path, json=body)).status_code == 201
    assert (
        await admin_client.patch(
            f"/api/admin/stores/{store.id}",
            json={"wash_count_enabled": False},
        )
    ).status_code == 200
    assert (
        await admin_client.put(
            first_path,
            json=body | {"daily_revenue": 180, "wash_count": 99},
        )
    ).status_code == 200
    assert (await admin_client.put(second_path, json=body | {"wash_count": 19})).status_code == 201

    assert (await admin_client.get(first_path)).json()["wash_count"] == 7
    assert (await admin_client.get(second_path)).json()["wash_count"] is None
    assert (
        await admin_client.patch(
            f"/api/admin/stores/{store.id}",
            json={"wash_count_enabled": True},
        )
    ).status_code == 200
    assert (await admin_client.get(first_path)).json()["wash_count"] == 7


async def test_rest_clears_historical_wash_count_while_setting_is_disabled(
    admin_client: AsyncClient, store_factory, db_session: AsyncSession
) -> None:
    store = await store_factory(name="Disabled rest normalization")
    await db_session.commit()
    path = f"/api/ledger/{store.id}/2026-07-20"
    body = {
        "is_open": "营业",
        "daily_revenue": 120,
        "wash_count": 7,
        "weather": None,
        "weather_edited": False,
        "activity": None,
        "items": [],
    }
    assert (await admin_client.put(path, json=body)).status_code == 201
    assert (
        await admin_client.patch(
            f"/api/admin/stores/{store.id}",
            json={"wash_count_enabled": False},
        )
    ).status_code == 200

    rested = await admin_client.put(path, json=body | {"is_open": "休息"})

    assert rested.status_code == 200
    assert (
        await admin_client.patch(
            f"/api/admin/stores/{store.id}",
            json={"wash_count_enabled": True},
        )
    ).status_code == 200
    assert (await admin_client.get(path)).json()["wash_count"] == 0


async def test_enabled_new_record_defaults_wash_count_to_zero_and_rejects_negative(
    admin_client: AsyncClient, store_factory, db_session: AsyncSession
) -> None:
    store = await store_factory(name="Default and validation")
    await db_session.commit()
    path = f"/api/ledger/{store.id}/2026-07-20"
    body = {
        "is_open": "营业",
        "daily_revenue": 120,
        "weather": None,
        "weather_edited": False,
        "activity": None,
        "items": [],
    }

    assert (await admin_client.put(path, json=body)).status_code == 201
    assert (await admin_client.get(path)).json()["wash_count"] == 0
    negative = await admin_client.put(
        f"/api/ledger/{store.id}/2026-07-21",
        json=body | {"wash_count": -1},
    )
    assert negative.status_code == 422
