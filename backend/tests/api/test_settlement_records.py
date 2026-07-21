from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import StoreMember
from app.models.ledger import StoreDailyRecord
from app.models.settlement import SettlementAuditEvent, SettlementCompany, SettlementRecord


@pytest.fixture
async def record_context(client, user_factory, store_factory, db_session):
    user = await user_factory(username="record-user", password="secret")
    store = await store_factory(name="Records", timezone="Pacific/Kiritimati")
    store.company_settlement_enabled = True
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.commit()
    response = await client.post(
        "/api/auth/login", json={"username": user.username, "password": "secret"}
    )
    assert response.status_code == 200
    return user, store


async def create_company(client: AsyncClient, store_id: int, name: str = "Alpha") -> dict:
    response = await client.post(
        f"/api/settlements/{store_id}/companies", json={"name": name}
    )
    assert response.status_code == 201
    return response.json()


async def create_record(
    client: AsyncClient, store_id: int, company_id: int, month: str, amount: int = 120
) -> dict:
    response = await client.post(
        f"/api/settlements/{store_id}/records",
        json={"company_id": company_id, "opening_month": month, "amount": amount},
    )
    assert response.status_code == 201
    return response.json()


async def test_create_pending_records_allows_duplicates_snapshots_name_and_audits(
    client: AsyncClient, record_context, db_session: AsyncSession
) -> None:
    _, store = record_context
    month = datetime.now(ZoneInfo(store.timezone)).strftime("%Y-%m")
    company = await create_company(client, store.id)

    first = await client.post(
        f"/api/settlements/{store.id}/records",
        json={"company_id": company["id"], "opening_month": month, "amount": 120},
    )
    second = await client.post(
        f"/api/settlements/{store.id}/records",
        json={"company_id": company["id"], "opening_month": month, "amount": 80},
    )
    assert first.status_code == second.status_code == 201
    assert first.json() | {"created_at": "ignored"} == {
        "id": first.json()["id"],
        "company_id": company["id"],
        "company_name": "Alpha",
        "opening_month": month,
        "amount": 120,
        "status": "pending",
        "revision": 1,
        "created_at": "ignored",
    }
    await client.patch(
        f"/api/settlements/{store.id}/companies/{company['id']}", json={"name": "Renamed"}
    )
    listed = (await client.get(f"/api/settlements/{store.id}/months/{month}")).json()
    assert [record["company_name"] for record in listed["records"]] == ["Alpha", "Alpha"]
    audits = list(
        await db_session.scalars(
            select(SettlementAuditEvent).where(
                SettlementAuditEvent.action == "settlement_record.create"
            )
        )
    )
    assert len(audits) == 2
    assert audits[0].after_state["status"] == "pending"


async def test_month_summary_uses_daily_ledger_and_stable_business_order(
    client: AsyncClient, record_context, db_session: AsyncSession
) -> None:
    user, store = record_context
    month = datetime.now(ZoneInfo(store.timezone)).date().replace(day=1)
    alpha = await create_company(client, store.id, "alpha")
    beta = await create_company(client, store.id, "Beta")
    db_session.add(
        StoreDailyRecord(
            store_id=store.id,
            date=month,
            daily_revenue=900,
            income_mode="legacy_total",
            wash_count=None,
            is_open="营业",
            weather=None,
            weather_auto=None,
            weather_code=None,
            temperature_max=None,
            temperature_min=None,
            precipitation=None,
            activity=None,
            created_by=user.id,
            updated_by=user.id,
        )
    )
    await db_session.commit()
    for company, amount in ((beta, 20), (alpha, 10), (alpha, 30)):
        response = await client.post(
            f"/api/settlements/{store.id}/records",
            json={
                "company_id": company["id"],
                "opening_month": month.strftime("%Y-%m"),
                "amount": amount,
            },
        )
        assert response.status_code == 201
    records = list(await db_session.scalars(select(SettlementRecord).order_by(SettlementRecord.id)))
    records[0].status = "confirmed"
    await db_session.commit()

    response = await client.get(
        f"/api/settlements/{store.id}/months/{month.strftime('%Y-%m')}"
    )
    assert response.status_code == 200
    body = response.json()
    assert [(item["status"], item["company_name"], item["amount"]) for item in body["records"]] == [
        ("pending", "alpha", 10),
        ("pending", "alpha", 30),
        ("confirmed", "Beta", 20),
    ]
    assert body | {"records": []} == {
        "opening_month": month.strftime("%Y-%m"),
        "records": [],
        "daily_ledger_revenue": 900,
        "confirmed_settlement_income": 20,
        "pending_amount": 40,
        "monthly_total": 920,
    }


@pytest.mark.parametrize(
    ("month", "amount"),
    [("2026-1", 1), ("2026-13", 1), ("not-a-month", 1), ("2026-01", 0), ("2026-01", -1), ("2026-01", 1.5), ("2026-01", "10"), ("2026-01", 10_000_000_000)],
)
async def test_create_rejects_invalid_months_and_non_positive_or_non_integer_amounts(
    client: AsyncClient, record_context, month: str, amount: object
) -> None:
    _, store = record_context
    company = await create_company(client, store.id)
    response = await client.post(
        f"/api/settlements/{store.id}/records",
        json={"company_id": company["id"], "opening_month": month, "amount": amount},
    )
    assert response.status_code == 422


async def test_rejects_future_month_in_store_timezone_and_cross_store_or_archived_company(
    client: AsyncClient, record_context, store_factory, db_session: AsyncSession
) -> None:
    user, store = record_context
    store_id = store.id
    company = await create_company(client, store_id)
    current = datetime.now(ZoneInfo(store.timezone)).date().replace(day=1)
    future = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    assert (
        await client.get(f"/api/settlements/{store_id}/months/{future.strftime('%Y-%m')}")
    ).status_code == 422

    other = await store_factory(name="Other")
    other.company_settlement_enabled = True
    foreign = SettlementCompany(
        store_id=other.id,
        name="Foreign",
        normalized_name="foreign",
        is_active=True,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(foreign)
    await db_session.commit()
    body = {"opening_month": current.strftime("%Y-%m"), "amount": 10}
    assert (
        await client.post(
            f"/api/settlements/{store_id}/records", json={**body, "company_id": foreign.id}
        )
    ).status_code == 404
    await client.post(f"/api/settlements/{store_id}/companies/{company['id']}/archive")
    assert (
        await client.post(
            f"/api/settlements/{store_id}/records", json={**body, "company_id": company["id"]}
        )
    ).status_code == 404


async def test_record_reads_and_writes_recheck_membership_and_feature_flag(
    client: AsyncClient, record_context, db_session: AsyncSession
) -> None:
    user, store = record_context
    user_id, store_id = user.id, store.id
    company = await create_company(client, store_id)
    month = datetime.now(ZoneInfo(store.timezone)).strftime("%Y-%m")
    record = await create_record(client, store_id, company["id"], month)
    membership = await db_session.scalar(
        select(StoreMember).where(
            StoreMember.store_id == store_id, StoreMember.user_id == user_id
        )
    )
    assert membership is not None
    await db_session.delete(membership)
    await db_session.commit()
    assert (await client.get(f"/api/settlements/{store_id}/months/{month}")).status_code == 403
    assert (
        await client.post(
            f"/api/settlements/{store_id}/records",
            json={"company_id": company["id"], "opening_month": month, "amount": 10},
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/settlements/{store_id}/records/{record['id']}",
            json={"amount": 20, "revision": 1},
        )
    ).status_code == 403
    assert (
        await client.request(
            "DELETE",
            f"/api/settlements/{store_id}/records/{record['id']}",
            json={"revision": 1},
        )
    ).status_code == 403

    db_session.add(StoreMember(store_id=store_id, user_id=user_id))
    fresh_store = await db_session.get(type(store), store_id)
    assert fresh_store is not None
    fresh_store.company_settlement_enabled = False
    await db_session.commit()
    assert (await client.get(f"/api/settlements/{store_id}/months/{month}")).status_code == 403
    assert (
        await client.patch(
            f"/api/settlements/{store_id}/records/{record['id']}",
            json={"amount": 20, "revision": 1},
        )
    ).status_code == 403
    assert (
        await client.request(
            "DELETE",
            f"/api/settlements/{store_id}/records/{record['id']}",
            json={"revision": 1},
        )
    ).status_code == 403


async def test_update_pending_record_changes_company_snapshot_amount_revision_and_audits(
    client: AsyncClient, record_context, db_session: AsyncSession
) -> None:
    user, store = record_context
    month = datetime.now(ZoneInfo(store.timezone)).strftime("%Y-%m")
    alpha = await create_company(client, store.id, "Alpha")
    beta = await create_company(client, store.id, "Beta")
    original = await create_record(client, store.id, alpha["id"], month)
    unchanged = await create_record(client, store.id, alpha["id"], month, amount=80)

    response = await client.patch(
        f"/api/settlements/{store.id}/records/{original['id']}",
        json={"company_id": beta["id"], "amount": 250, "revision": 1},
    )

    assert response.status_code == 200
    assert response.json() | {"created_at": "ignored"} == {
        "id": original["id"],
        "company_id": beta["id"],
        "company_name": "Beta",
        "opening_month": month,
        "amount": 250,
        "status": "pending",
        "revision": 2,
        "created_at": "ignored",
    }
    audit = await db_session.scalar(
        select(SettlementAuditEvent).where(
            SettlementAuditEvent.action == "settlement_record.update",
            SettlementAuditEvent.entity_id == original["id"],
        )
    )
    assert audit is not None
    assert audit.actor_id == user.id
    assert audit.before_state["company_name"] == "Alpha"
    assert audit.after_state["company_name"] == "Beta"
    historical = await db_session.get(SettlementRecord, unchanged["id"])
    assert historical is not None
    assert historical.company_name == "Alpha"


async def test_update_with_stale_revision_returns_canonical_record_without_overwrite(
    client: AsyncClient, record_context
) -> None:
    _, store = record_context
    store_id = store.id
    month = datetime.now(ZoneInfo(store.timezone)).strftime("%Y-%m")
    company = await create_company(client, store_id)
    original = await create_record(client, store_id, company["id"], month)
    first = await client.patch(
        f"/api/settlements/{store_id}/records/{original['id']}",
        json={"amount": 200, "revision": 1},
    )
    assert first.status_code == 200

    stale = await client.patch(
        f"/api/settlements/{store_id}/records/{original['id']}",
        json={"amount": 999, "revision": 1},
    )

    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "settlement_record_revision_conflict",
        "message": "开票记录已被其他用户修改，请重新加载后再试",
        "current_record": first.json(),
    }
    listed = (await client.get(f"/api/settlements/{store_id}/months/{month}")).json()
    assert listed["records"][0]["amount"] == 200


async def test_delete_pending_record_requires_current_revision_and_audits(
    client: AsyncClient, record_context, db_session: AsyncSession
) -> None:
    user, store = record_context
    store_id = store.id
    month = datetime.now(ZoneInfo(store.timezone)).strftime("%Y-%m")
    company = await create_company(client, store_id)
    original = await create_record(client, store_id, company["id"], month)

    stale = await client.request(
        "DELETE",
        f"/api/settlements/{store_id}/records/{original['id']}",
        json={"revision": 2},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_record"]["revision"] == 1

    deleted = await client.request(
        "DELETE",
        f"/api/settlements/{store_id}/records/{original['id']}",
        json={"revision": 1},
    )
    assert deleted.status_code == 204
    assert await db_session.get(SettlementRecord, original["id"]) is None
    audit = await db_session.scalar(
        select(SettlementAuditEvent).where(
            SettlementAuditEvent.action == "settlement_record.delete",
            SettlementAuditEvent.entity_id == original["id"],
        )
    )
    assert audit is not None
    assert audit.actor_id == user.id
    assert audit.before_state["revision"] == 1
    assert audit.after_state is None


async def test_confirmed_record_rejects_direct_update_and_delete(
    client: AsyncClient, record_context, db_session: AsyncSession
) -> None:
    _, store = record_context
    store_id = store.id
    month = datetime.now(ZoneInfo(store.timezone)).strftime("%Y-%m")
    company = await create_company(client, store_id)
    original = await create_record(client, store_id, company["id"], month)
    record = await db_session.get(SettlementRecord, original["id"])
    assert record is not None
    record.status = "confirmed"
    await db_session.commit()

    updated = await client.patch(
        f"/api/settlements/{store_id}/records/{original['id']}",
        json={"amount": 200, "revision": 1},
    )
    deleted = await client.request(
        "DELETE",
        f"/api/settlements/{store_id}/records/{original['id']}",
        json={"revision": 1},
    )

    assert updated.status_code == deleted.status_code == 409
    assert updated.json()["detail"] == "已确认开票记录必须先撤销到账确认"
    assert deleted.json()["detail"] == "已确认开票记录必须先撤销到账确认"


@pytest.mark.parametrize(
    "body",
    [
        {"revision": 1},
        {"amount": 0, "revision": 1},
        {"amount": -1, "revision": 1},
        {"amount": 1.5, "revision": 1},
        {"amount": "20", "revision": 1},
        {"amount": 10_000_000_000, "revision": 1},
        {"amount": 20, "revision": 1.5},
    ],
)
async def test_update_rejects_missing_changes_or_invalid_amount_and_revision(
    client: AsyncClient, record_context, body: dict[str, object]
) -> None:
    _, store = record_context
    month = datetime.now(ZoneInfo(store.timezone)).strftime("%Y-%m")
    company = await create_company(client, store.id)
    record = await create_record(client, store.id, company["id"], month)

    response = await client.patch(
        f"/api/settlements/{store.id}/records/{record['id']}", json=body
    )

    assert response.status_code == 422


async def test_update_and_delete_reject_records_owned_by_another_store(
    client: AsyncClient, record_context, store_factory, db_session: AsyncSession
) -> None:
    user, store = record_context
    store_id = store.id
    other = await store_factory(name="Foreign Records")
    other.company_settlement_enabled = True
    company = SettlementCompany(
        store_id=other.id,
        name="Foreign",
        normalized_name="foreign",
        is_active=True,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(company)
    await db_session.flush()
    foreign_record = SettlementRecord(
        store_id=other.id,
        company_id=company.id,
        company_name=company.name,
        opening_month=date(2026, 7, 1),
        amount=100,
        status="pending",
        revision=1,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(foreign_record)
    await db_session.commit()
    foreign_record_id = foreign_record.id

    updated = await client.patch(
        f"/api/settlements/{store_id}/records/{foreign_record_id}",
        json={"amount": 200, "revision": 1},
    )
    deleted = await client.request(
        "DELETE",
        f"/api/settlements/{store_id}/records/{foreign_record_id}",
        json={"revision": 1},
    )

    assert updated.status_code == deleted.status_code == 404
