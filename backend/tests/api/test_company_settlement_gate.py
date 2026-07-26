from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.identity import StoreMember, User
from app.models.settlement import (
    SettlementAuditEvent,
    SettlementCompany,
    SettlementRecord,
)


@pytest.fixture
async def admin_client(
    client: AsyncClient, user_factory, db_session: AsyncSession
) -> AsyncClient:
    await user_factory(username="settlement-admin", password="secret", role="admin")
    response = await client.post(
        "/api/auth/login",
        json={"username": "settlement-admin", "password": "secret"},
    )
    assert response.status_code == 200
    await db_session.commit()
    return client


async def test_admin_can_toggle_only_the_target_store_and_change_is_audited(
    admin_client, store_factory, db_session
) -> None:
    first = await store_factory(name="First")
    second = await store_factory(name="Second")
    await db_session.commit()
    actor = await db_session.scalar(
        select(User).where(User.username == "settlement-admin")
    )
    assert actor is not None

    response = await admin_client.patch(
        f"/api/admin/stores/{first.id}",
        json={"company_settlement_enabled": True},
    )

    assert response.status_code == 200
    assert response.json()["company_settlement_enabled"] is True
    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.company_settlement_enabled is True
    assert second.company_settlement_enabled is False
    event = await db_session.scalar(select(SettlementAuditEvent))
    assert event is not None
    assert (event.store_id, event.actor_id, event.action, event.entity_type, event.entity_id) == (
        first.id,
        actor.id,
        "company_settlement.toggle",
        "store",
        first.id,
    )
    assert event.before_state == {"company_settlement_enabled": False}
    assert event.after_state == {"company_settlement_enabled": True}

    unchanged = await admin_client.patch(
        f"/api/admin/stores/{first.id}",
        json={"company_settlement_enabled": True},
    )
    assert unchanged.status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(SettlementAuditEvent)) == 1


async def test_regular_user_cannot_modify_the_store_flag(
    auth_client, store_factory
) -> None:
    store = await store_factory(name="Denied")

    response = await auth_client.patch(
        f"/api/admin/stores/{store.id}",
        json={"company_settlement_enabled": True},
    )

    assert response.status_code == 403


async def test_accessible_store_payload_exposes_server_flag_and_gate_is_store_scoped(
    client, user_factory, store_factory, db_session
) -> None:
    member = await user_factory(username="settlement-member", password="secret")
    enabled = await store_factory(name="Enabled")
    enabled.company_settlement_enabled = True
    disabled = await store_factory(name="Disabled")
    other = await store_factory(name="Other")
    other.company_settlement_enabled = True
    db_session.add_all(
        [
            StoreMember(store_id=enabled.id, user_id=member.id),
            StoreMember(store_id=disabled.id, user_id=member.id),
        ]
    )
    await db_session.flush()
    await db_session.commit()
    await client.post(
        "/api/auth/login",
        json={"username": member.username, "password": "secret"},
    )

    stores = await client.get("/api/stores/accessible")
    by_id = {item["id"]: item for item in stores.json()}
    assert by_id[enabled.id]["company_settlement_enabled"] is True
    assert by_id[disabled.id]["company_settlement_enabled"] is False
    assert other.id not in by_id
    assert (await client.get(f"/api/settlements/{enabled.id}")).status_code == 200
    denied = await client.get(f"/api/settlements/{disabled.id}")
    assert denied.status_code == 403
    assert denied.json() == {"detail": "当前门店未启用公司结算"}
    assert (await client.get(f"/api/settlements/{other.id}")).status_code == 403


async def test_all_store_roles_can_read_enabled_company_settlement(
    client,
    user_factory,
    store_factory,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "settlement-owner")
    get_settings.cache_clear()
    member = await user_factory(username="settlement-member", password="secret")
    admin = await user_factory(
        username="settlement-admin-reader",
        password="secret",
        role="admin",
    )
    owner = await user_factory(username="settlement-owner", password="secret")
    store = await store_factory(name="Shared enabled store")
    store.company_settlement_enabled = True
    db_session.add(StoreMember(store_id=store.id, user_id=member.id))
    company = SettlementCompany(
        store_id=store.id,
        name="Shared Fleet",
        normalized_name="shared fleet",
        is_active=True,
        created_by=admin.id,
        updated_by=admin.id,
    )
    db_session.add(company)
    await db_session.flush()
    db_session.add(
        SettlementRecord(
            store_id=store.id,
            company_id=company.id,
            company_name=company.name,
            opening_month=date(2026, 7, 1),
            amount=420,
            status="confirmed",
            revision=1,
            created_by=admin.id,
            updated_by=admin.id,
        )
    )
    await db_session.commit()

    for user in (member, admin, owner):
        login = await client.post(
            "/api/auth/login",
            json={"username": user.username, "password": "secret"},
        )
        assert login.status_code == 200
        if user is owner:
            assert login.json()["role"] == "admin"
            assert login.json()["is_owner"] is True

        stores = await client.get("/api/stores/accessible")
        assert stores.status_code == 200
        assert stores.json() == [
            {
                "id": store.id,
                "name": store.name,
                "timezone": store.timezone,
                "is_active": True,
                "company_settlement_enabled": True,
                "wash_count_enabled": True,
            }
        ]
        workspace = await client.get(f"/api/settlements/{store.id}")
        assert workspace.status_code == 200
        assert workspace.json()["company_settlement_enabled"] is True
        companies = await client.get(f"/api/settlements/{store.id}/companies")
        assert companies.status_code == 200
        assert [item["name"] for item in companies.json()] == ["Shared Fleet"]
        month = await client.get(f"/api/settlements/{store.id}/months/2026-07")
        assert month.status_code == 200
        assert [item["amount"] for item in month.json()["records"]] == [420]
        await client.post("/api/auth/logout")


async def test_new_store_defaults_disabled_and_admin_payload_exposes_flag(
    admin_client,
) -> None:
    created = await admin_client.post(
        "/api/admin/stores",
        json={
            "name": "Default off",
            "address": "Milan",
            "latitude": "45.0",
            "longitude": "9.0",
            "timezone": "Europe/Rome",
        },
    )

    assert created.status_code == 201
    assert created.json()["company_settlement_enabled"] is False
    listed = await admin_client.get("/api/admin/stores")
    assert listed.json()[0]["company_settlement_enabled"] is False


async def test_toggling_off_and_on_preserves_existing_settlement_history(
    admin_client, store_factory, db_session
) -> None:
    store = await store_factory(name="History")
    store.company_settlement_enabled = True
    actor = await db_session.scalar(
        select(User).where(User.username == "settlement-admin")
    )
    assert actor is not None
    company = SettlementCompany(
        store_id=store.id,
        name="Fleet",
        normalized_name="fleet",
        is_active=True,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db_session.add(company)
    await db_session.flush()
    db_session.add(
        SettlementRecord(
            store_id=store.id,
            company_id=company.id,
            company_name=company.name,
            opening_month=date(2026, 6, 1),
            amount=420,
            status="confirmed",
            revision=1,
            created_by=actor.id,
            updated_by=actor.id,
        )
    )
    await db_session.commit()

    disabled = await admin_client.patch(
        f"/api/admin/stores/{store.id}",
        json={"company_settlement_enabled": False},
    )
    enabled = await admin_client.patch(
        f"/api/admin/stores/{store.id}",
        json={"company_settlement_enabled": True},
    )

    assert disabled.status_code == enabled.status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(SettlementCompany)) == 1
    assert await db_session.scalar(select(func.count()).select_from(SettlementRecord)) == 1
    record = await db_session.scalar(select(SettlementRecord))
    assert record is not None
    assert (record.status, record.amount, record.revision) == ("confirmed", 420, 1)
    assert await db_session.scalar(select(func.count()).select_from(SettlementAuditEvent)) == 2
