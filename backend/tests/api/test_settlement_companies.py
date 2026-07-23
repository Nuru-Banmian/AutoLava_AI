from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import StoreMember, User
from app.models.settlement import SettlementAuditEvent, SettlementCompany, SettlementRecord


@pytest.fixture
async def settlement_context(client, user_factory, store_factory, db_session):
    user = await user_factory(username="directory-user", password="secret")
    store = await store_factory(name="Directory")
    store.company_settlement_enabled = True
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.commit()
    assert (
        await client.post("/api/auth/login", json={"username": user.username, "password": "secret"})
    ).status_code == 200
    return user, store


async def test_create_normalizes_lists_stably_and_scopes_uniqueness(
    client: AsyncClient, settlement_context, store_factory, db_session: AsyncSession
) -> None:
    user, store = settlement_context
    store_id = store.id
    second = await store_factory(name="Second")
    second_id = second.id
    second.company_settlement_enabled = True
    db_session.add(StoreMember(store_id=second.id, user_id=user.id))
    await db_session.commit()

    created = await client.post(
        f"/api/settlements/{store_id}/companies", json={"name": "  Beta   Fleet  "}
    )
    alpha = await client.post(f"/api/settlements/{store_id}/companies", json={"name": "alpha"})

    assert created.status_code == alpha.status_code == 201
    assert created.json()["name"] == "Beta Fleet"
    duplicate = await client.post(
        f"/api/settlements/{store_id}/companies", json={"name": " beta fleet "}
    )
    assert duplicate.status_code == 409
    assert (
        await client.post(f"/api/settlements/{second_id}/companies", json={"name": "BETA FLEET"})
    ).status_code == 201

    listed = await client.get(f"/api/settlements/{store_id}/companies")
    assert [item["name"] for item in listed.json()] == ["alpha", "Beta Fleet"]
    assert all(set(item) == {"id", "name", "is_active"} for item in listed.json())
    assert await db_session.scalar(select(func.count()).select_from(SettlementAuditEvent)) == 3


@pytest.mark.parametrize("name", ["", "   ", "x" * 121])
async def test_create_rejects_invalid_names(
    client: AsyncClient, settlement_context, name: str
) -> None:
    _, store = settlement_context
    response = await client.post(f"/api/settlements/{store.id}/companies", json={"name": name})
    assert response.status_code == 422


async def test_rename_archive_restore_delete_and_audit(
    client: AsyncClient, settlement_context, db_session: AsyncSession
) -> None:
    _, store = settlement_context
    store_id = store.id
    first = (
        await client.post(f"/api/settlements/{store_id}/companies", json={"name": "First"})
    ).json()
    second = (
        await client.post(f"/api/settlements/{store_id}/companies", json={"name": "Second"})
    ).json()

    renamed = await client.patch(
        f"/api/settlements/{store_id}/companies/{first['id']}",
        json={"name": "  Renamed   Company "},
    )
    assert renamed.json()["name"] == "Renamed Company"
    assert (
        await client.patch(
            f"/api/settlements/{store_id}/companies/{first['id']}",
            json={"name": "SECOND"},
        )
    ).status_code == 409

    archived = await client.post(f"/api/settlements/{store_id}/companies/{first['id']}/archive")
    assert archived.json()["is_active"] is False
    assert [
        item["id"] for item in (await client.get(f"/api/settlements/{store_id}/companies")).json()
    ] == [second["id"]]
    assert [
        item["id"]
        for item in (
            await client.get(f"/api/settlements/{store_id}/companies?archived=true")
        ).json()
    ] == [first["id"]]

    archive_rename = await client.patch(
        f"/api/settlements/{store_id}/companies/{first['id']}", json={"name": "Old Fleet"}
    )
    assert archive_rename.status_code == 200
    assert (
        await client.post(f"/api/settlements/{store_id}/companies/{first['id']}/restore")
    ).json()["is_active"] is True
    assert (
        await client.delete(f"/api/settlements/{store_id}/companies/{first['id']}")
    ).status_code == 204
    assert await db_session.get(SettlementCompany, first["id"]) is None
    actions = list(
        await db_session.scalars(
            select(SettlementAuditEvent.action).order_by(SettlementAuditEvent.id)
        )
    )
    assert actions == [
        "settlement_company.create",
        "settlement_company.create",
        "settlement_company.rename",
        "settlement_company.archive",
        "settlement_company.rename",
        "settlement_company.restore",
        "settlement_company.delete",
    ]


async def test_historical_company_cannot_be_deleted_but_can_be_archived(
    client: AsyncClient, settlement_context, db_session: AsyncSession
) -> None:
    user, store = settlement_context
    company = SettlementCompany(
        store_id=store.id,
        name="History",
        normalized_name="history",
        is_active=True,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(company)
    await db_session.flush()
    db_session.add(
        SettlementRecord(
            store_id=store.id,
            company_id=company.id,
            company_name="History",
            opening_month=date(2026, 7, 1),
            amount=100,
            status="pending",
            revision=1,
            created_by=user.id,
            updated_by=user.id,
        )
    )
    await db_session.commit()
    store_id = store.id
    company_id = company.id

    denied = await client.delete(f"/api/settlements/{store_id}/companies/{company_id}")
    assert denied.status_code == 409
    assert "只能归档" in denied.json()["detail"]
    assert (
        await client.post(f"/api/settlements/{store_id}/companies/{company_id}/archive")
    ).status_code == 200


async def test_archiving_releases_name_and_restore_rejects_active_conflict(
    client: AsyncClient, settlement_context, db_session: AsyncSession
) -> None:
    _, store = settlement_context
    store_id = store.id
    archived = (
        await client.post(f"/api/settlements/{store_id}/companies", json={"name": "Shared Fleet"})
    ).json()
    assert (
        await client.post(f"/api/settlements/{store_id}/companies/{archived['id']}/archive")
    ).status_code == 200

    replacement = await client.post(
        f"/api/settlements/{store_id}/companies", json={"name": " shared fleet "}
    )
    assert replacement.status_code == 201
    renamed_archived = await client.patch(
        f"/api/settlements/{store_id}/companies/{archived['id']}",
        json={"name": "SHARED FLEET"},
    )
    assert renamed_archived.status_code == 200
    assert renamed_archived.json()["is_active"] is False

    restore = await client.post(f"/api/settlements/{store_id}/companies/{archived['id']}/restore")
    assert restore.status_code == 409
    assert restore.json() == {"detail": "该门店已有同名活动结算公司，无法恢复"}
    stored = await db_session.get(SettlementCompany, archived["id"])
    assert stored is not None
    assert stored.is_active is False


async def test_every_operation_rechecks_access_flag_and_company_store_scope(
    client: AsyncClient, settlement_context, store_factory, db_session: AsyncSession
) -> None:
    _, store = settlement_context
    store_id = store.id
    other = await store_factory(name="Private")
    other.company_settlement_enabled = True
    actor = await db_session.scalar(select(User).where(User.username == "directory-user"))
    assert actor
    private = SettlementCompany(
        store_id=other.id,
        name="Private Co",
        normalized_name="private co",
        is_active=True,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db_session.add(private)
    await db_session.commit()

    assert (await client.get(f"/api/settlements/{other.id}/companies")).status_code == 403
    assert (
        await client.patch(
            f"/api/settlements/{store_id}/companies/{private.id}", json={"name": "Stolen"}
        )
    ).status_code == 404
    assert (await client.get(f"/api/settlements/{store_id}/companies")).json() == []

    store = await db_session.get(type(store), store_id)
    assert store is not None
    store.company_settlement_enabled = False
    await db_session.commit()
    assert (await client.get(f"/api/settlements/{store_id}/companies")).status_code == 403
    assert (
        await client.post(f"/api/settlements/{store_id}/companies", json={"name": "Denied"})
    ).status_code == 403
