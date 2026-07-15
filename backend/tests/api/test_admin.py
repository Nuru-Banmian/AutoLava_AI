from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.identity import StoreMember, StoreSetting
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.operations import DailyBriefing, ScheduledTaskLog, SystemAlert


@pytest.fixture
async def admin_client(client, user_factory) -> AsyncClient:
    await user_factory(username="administrator", password="secret", role="admin")
    response = await client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "secret", "remember": False},
    )
    assert response.status_code == 200
    return client


@pytest.fixture
async def category_with_item(db_session, store_factory, user_factory) -> IncomeCategory:
    user = await user_factory(username="ledger-owner", password="secret")
    store = await store_factory(name="Used Category Store")
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
        weather=None,
        weather_auto=None,
        weather_code=None,
        temperature_max=None,
        temperature_min=None,
        precipitation=None,
        activity=None,
        weather_edited=False,
        scanned=False,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(record)
    await db_session.flush()
    db_session.add(
        DailyIncomeItem(record_id=record.id, category_id=category.id, amount=Decimal("25.00"))
    )
    await db_session.flush()
    return category


async def test_regular_user_cannot_create_user(auth_client) -> None:
    response = await auth_client.post(
        "/api/admin/users",
        json={"username": "new-user", "password": "secret123", "role": "user"},
    )
    assert response.status_code == 403


async def test_geocode_is_admin_only(auth_client) -> None:
    denied = await auth_client.get("/api/admin/stores/geocode", params={"query": "Milano"})
    assert denied.status_code == 403


async def test_admin_geocode_is_normalized(admin_client, open_meteo_app, respx_mock) -> None:
    respx_mock.get("https://geocoding-api.open-meteo.com/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "name": "Milano",
                        "latitude": 45.46,
                        "longitude": 9.19,
                        "country": "Italia",
                        "timezone": "Europe/Rome",
                    }
                ]
            },
        )
    )
    response = await admin_client.get("/api/admin/stores/geocode", params={"query": "Milano"})
    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "Milano",
            "latitude": 45.46,
            "longitude": 9.19,
            "country": "Italia",
            "timezone": "Europe/Rome",
        }
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"name": " ", "address": "Via", "latitude": 45, "longitude": 9, "timezone": "Europe/Rome"},
        {"name": "x" * 121, "address": "Via", "latitude": 45, "longitude": 9, "timezone": "Europe/Rome"},
        {"name": "Roma", "address": " ", "latitude": 45, "longitude": 9, "timezone": "Europe/Rome"},
        {"name": "Roma", "address": "x" * 256, "latitude": 45, "longitude": 9, "timezone": "Europe/Rome"},
        {"name": "Roma", "address": "Via", "latitude": 91, "longitude": 9, "timezone": "Europe/Rome"},
        {"name": "Roma", "address": "Via", "latitude": 45, "longitude": -181, "timezone": "Europe/Rome"},
        {"name": "Roma", "address": "Via", "latitude": 45, "longitude": 9, "timezone": "Mars/Olympus"},
    ],
)
async def test_store_create_rejects_invalid_boundary_values(admin_client, body) -> None:
    assert (await admin_client.post("/api/admin/stores", json=body)).status_code == 422


async def test_store_patch_and_category_boundaries_return_422(admin_client, store_factory) -> None:
    store = await store_factory(name="Boundary")
    assert (await admin_client.patch(f"/api/admin/stores/{store.id}", json={"timezone": "bad/zone"})).status_code == 422
    assert (await admin_client.post("/api/admin/income-categories", json={
        "store_id": store.id, "name": " ", "include_in_total": True, "sort_order": 0,
    })).status_code == 422
    assert (await admin_client.post("/api/admin/income-categories", json={
        "store_id": store.id, "name": "x" * 101, "include_in_total": True, "sort_order": 0,
    })).status_code == 422


async def test_admin_can_create_list_patch_and_audit_users(
    admin_client, db_session: AsyncSession
) -> None:
    created = await admin_client.post(
        "/api/admin/users",
        json={"username": "zoe", "password": "first-secret", "role": "user"},
    )
    assert created.status_code == 201
    assert created.json() == {
        "id": created.json()["id"],
        "username": "zoe",
        "role": "user",
        "is_active": True,
    }
    user_id = created.json()["id"]

    patched = await admin_client.patch(
        f"/api/admin/users/{user_id}",
        json={"password": "second-secret", "is_active": False},
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False

    users = await admin_client.get("/api/admin/users")
    assert users.status_code == 200
    assert [item["username"] for item in users.json()] == ["administrator", "zoe"]

    audits = (
        await db_session.scalars(
            select(AuditLog)
            .where(AuditLog.operation_domain == "admin", AuditLog.record_id == user_id)
            .order_by(AuditLog.id)
        )
    ).all()
    assert [audit.operation_type for audit in audits] == ["create", "update"]
    assert audits[0].before_json is None
    assert audits[0].after_json == {
        "id": user_id,
        "username": "zoe",
        "role": "user",
        "is_active": True,
        "password_changed": True,
    }
    assert audits[1].before_json == {
        "id": user_id,
        "username": "zoe",
        "role": "user",
        "is_active": True,
        "password_changed": True,
    }
    assert audits[1].after_json == {
        "id": user_id,
        "username": "zoe",
        "role": "user",
        "is_active": False,
        "password_changed": True,
    }
    assert "hash" not in str([audit.before_json for audit in audits])
    assert "hash" not in str([audit.after_json for audit in audits])


async def test_duplicate_username_returns_409_and_keeps_transaction_usable(
    admin_client,
) -> None:
    body = {"username": "duplicate", "password": "secret123", "role": "user"}
    created = await admin_client.post("/api/admin/users", json=body)
    assert created.status_code == 201

    duplicate = await admin_client.post("/api/admin/users", json=body)
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Username already exists"}

    listed = await admin_client.get("/api/admin/users")
    assert listed.status_code == 200
    assert [user["username"] for user in listed.json()].count("duplicate") == 1


async def test_admin_lists_user_stores_and_operation_history(
    admin_client, user_factory, store_factory, db_session: AsyncSession
) -> None:
    user = await user_factory(username="family", password="secret")
    zulu = await store_factory(name="Zulu")
    alpha = await store_factory(name="Alpha")
    db_session.add_all(
        [
            StoreMember(store_id=zulu.id, user_id=user.id),
            StoreMember(store_id=alpha.id, user_id=user.id),
            AuditLog(
                operation_domain="ledger",
                store_id=alpha.id,
                record_id=9,
                record_date=date(2026, 7, 12),
                operation_type="update",
                operation_source="manual",
                operator_user_id=user.id,
                before_json={"value": 1},
                after_json={"value": 2},
                description="Changed a record",
                requires_approval=False,
                approved=True,
            ),
        ]
    )
    await db_session.flush()

    stores = await admin_client.get(f"/api/admin/users/{user.id}/stores")
    assert stores.status_code == 200
    assert [item["name"] for item in stores.json()] == ["Alpha", "Zulu"]
    assert stores.json()[0] == {
        "id": alpha.id,
        "name": "Alpha",
        "address": "Alpha address",
        "latitude": "45.000000",
        "longitude": "9.000000",
        "timezone": "Europe/Rome",
        "is_active": True,
    }

    operations = await admin_client.get(f"/api/admin/users/{user.id}/operations")
    assert operations.status_code == 200
    assert len(operations.json()) == 1
    assert operations.json()[0] | {
        "id": operations.json()[0]["id"],
        "created_at": operations.json()[0]["created_at"],
    } == {
        "id": operations.json()[0]["id"],
        "operation_domain": "ledger",
        "store_id": alpha.id,
        "record_id": 9,
        "record_date": "2026-07-12",
        "operation_type": "update",
        "operation_source": "manual",
        "before": {"value": 1},
        "after": {"value": 2},
        "description": "Changed a record",
            "approved": True,
            "rollbackable": True,
            "created_at": operations.json()[0]["created_at"],
    }


async def test_admin_can_create_list_patch_stores_with_default_setting_and_audits(
    admin_client, db_session: AsyncSession
) -> None:
    zulu = await admin_client.post(
        "/api/admin/stores",
        json={
            "name": "Zulu",
            "address": "Old address",
            "latitude": "45.123456",
            "longitude": "9.654321",
            "timezone": "Europe/Rome",
        },
    )
    assert zulu.status_code == 201
    store_id = zulu.json()["id"]
    setting = await db_session.get(StoreSetting, store_id)
    assert setting is not None
    assert setting.standard_work_hours == 8

    alpha = await admin_client.post(
        "/api/admin/stores",
        json={
            "name": "Alpha",
            "address": "Alpha address",
            "latitude": "44.000001",
            "longitude": "8.000001",
        },
    )
    assert alpha.status_code == 201
    patched = await admin_client.patch(
        f"/api/admin/stores/{store_id}",
        json={"address": "New address", "timezone": "Europe/Berlin", "is_active": False},
    )
    assert patched.status_code == 200
    assert patched.json() == {
        "id": store_id,
        "name": "Zulu",
        "address": "New address",
        "latitude": "45.123456",
        "longitude": "9.654321",
        "timezone": "Europe/Berlin",
        "is_active": False,
    }

    listed = await admin_client.get("/api/admin/stores")
    assert listed.status_code == 200
    assert [store["name"] for store in listed.json()] == ["Alpha", "Zulu"]

    audits = (
        await db_session.scalars(
            select(AuditLog)
            .where(AuditLog.operation_domain == "admin", AuditLog.record_id == store_id)
            .order_by(AuditLog.id)
        )
    ).all()
    assert [audit.operation_type for audit in audits] == ["create", "update"]
    assert audits[0].store_id == store_id
    assert audits[0].before_json is None
    assert audits[0].after_json["address"] == "Old address"
    assert audits[0].after_json["standard_work_hours"] == 8
    assert audits[1].before_json["address"] == "Old address"
    assert audits[1].after_json["address"] == "New address"


async def test_admin_can_assign_exact_store_members(
    admin_client, user_factory, store_factory, db_session: AsyncSession
) -> None:
    removed = await user_factory(username="removed", password="secret")
    family = await user_factory(username="family", password="secret")
    first = await store_factory(name="First")
    second = await store_factory(name="Second")
    db_session.add(StoreMember(store_id=first.id, user_id=removed.id))
    await db_session.flush()

    response = await admin_client.put(
        f"/api/admin/stores/{first.id}/members",
        json={"user_ids": [family.id, family.id]},
    )
    assert response.status_code == 200
    assert response.json() == {"store_id": first.id, "user_ids": [family.id]}
    members = await admin_client.get(f"/api/admin/stores/{first.id}/members")
    assert members.status_code == 200
    assert members.json() == [
        {
            "id": family.id,
            "username": "family",
            "role": "user",
            "is_active": True,
        }
    ]
    accessible = await admin_client.get(f"/api/admin/users/{family.id}/stores")
    assert [item["id"] for item in accessible.json()] == [first.id]
    assert second.id not in [item["id"] for item in accessible.json()]

    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.operation_domain == "admin",
            AuditLog.store_id == first.id,
            AuditLog.operation_type == "update",
        )
    )
    assert audit is not None
    assert audit.before_json == {"store_id": first.id, "user_ids": [removed.id]}
    assert audit.after_json == {"store_id": first.id, "user_ids": [family.id]}


async def test_admin_can_create_list_and_patch_income_categories(
    admin_client, store_factory, db_session: AsyncSession
) -> None:
    store = await store_factory(name="Categories")
    later = await admin_client.post(
        "/api/admin/income-categories",
        json={"store_id": store.id, "name": "Later", "include_in_total": False, "sort_order": 5},
    )
    assert later.status_code == 201
    first = await admin_client.post(
        "/api/admin/income-categories",
        json={"store_id": store.id, "name": "First", "include_in_total": True},
    )
    assert first.status_code == 201

    listed = await admin_client.get("/api/admin/income-categories", params={"store_id": store.id})
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["First", "Later"]

    category_id = later.json()["id"]
    patched = await admin_client.patch(
        f"/api/admin/income-categories/{category_id}",
        json={"name": "Updated", "is_active": False, "sort_order": 1},
    )
    assert patched.status_code == 200
    assert patched.json() == {
        "id": category_id,
        "store_id": store.id,
        "name": "Updated",
        "include_in_total": False,
        "is_active": False,
        "sort_order": 1,
    }

    audits = (
        await db_session.scalars(
            select(AuditLog)
            .where(AuditLog.operation_domain == "admin", AuditLog.record_id == category_id)
            .order_by(AuditLog.id)
        )
    ).all()
    assert [audit.operation_type for audit in audits] == ["create", "update"]
    assert audits[0].before_json is None
    assert audits[0].after_json["name"] == "Later"
    assert audits[1].before_json["name"] == "Later"
    assert audits[1].after_json["name"] == "Updated"


async def test_include_in_total_change_recomputes_and_audits_every_affected_record(
    admin_client,
    user_factory,
    store_factory,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 14, 12, tzinfo=tz)

    monkeypatch.setattr("app.api.routes.admin.datetime", FrozenDateTime)
    owner = await user_factory(username="record-owner", password="secret")
    store = await store_factory(name="Revenue")
    included = IncomeCategory(
        store_id=store.id,
        name="Included",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    other = IncomeCategory(
        store_id=store.id,
        name="Other",
        include_in_total=True,
        is_active=True,
        sort_order=1,
    )
    db_session.add_all([included, other])
    await db_session.flush()
    records = [
        StoreDailyRecord(
            store_id=store.id,
            date=date(2026, 7, day),
            daily_revenue=Decimal("35.00"),
            wash_count=day,
            is_open="营业",
            weather="sunny",
            weather_auto="sunny",
            weather_code=1,
            temperature_max=Decimal("28.50"),
            temperature_min=Decimal("17.25"),
            precipitation=Decimal("0.00"),
            activity=f"day {day}",
            weather_edited=False,
            scanned=True,
            created_by=owner.id,
            updated_by=owner.id,
        )
        for day in (12, 13)
    ]
    db_session.add_all(records)
    await db_session.flush()
    for record in records:
        db_session.add_all(
            [
                DailyIncomeItem(
                    record_id=record.id, category_id=included.id, amount=Decimal("25.00")
                ),
                DailyIncomeItem(record_id=record.id, category_id=other.id, amount=Decimal("10.00")),
            ]
        )
    await db_session.flush()

    db_session.add(
        DailyBriefing(
            store_id=store.id,
            card_type="yesterday",
            content="stale €35.00",
        )
    )
    await db_session.flush()

    response = await admin_client.patch(
        f"/api/admin/income-categories/{included.id}",
        json={"include_in_total": False},
    )
    assert response.status_code == 200
    dashboard = await admin_client.get(f"/api/dashboard/{store.id}")
    assert dashboard.json()[0]["content"].startswith("昨天营业，营业额 €10.00")
    for record in records:
        await db_session.refresh(record)
        assert record.daily_revenue == Decimal("10.00")

    ledger_audits = (
        await db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.operation_domain == "ledger",
                AuditLog.operation_source == "system",
                AuditLog.record_id.in_([record.id for record in records]),
            )
            .order_by(AuditLog.record_id)
        )
    ).all()
    assert len(ledger_audits) == 2
    assert [audit.store_id for audit in ledger_audits] == [store.id, store.id]
    assert [audit.record_date for audit in ledger_audits] == [record.date for record in records]
    for audit in ledger_audits:
        assert audit.operation_type == "update"
        assert audit.rollbackable is False
        assert audit.before_json["daily_revenue"] == "35.00"
        assert audit.after_json["daily_revenue"] == "10.00"
        assert audit.before_json["wash_count"] in (12, 13)
        assert audit.before_json["items"] == audit.after_json["items"]
        assert {item["amount"] for item in audit.before_json["items"]} == {"10.00", "25.00"}
        assert {"created_at", "updated_at"} <= audit.before_json.keys()
        assert {"created_at", "updated_at"} <= audit.before_json["items"][0].keys()

    history = await admin_client.get(f"/api/database/{store.id}/history")
    system_entries = [entry for entry in history.json() if entry["operation_source"] == "system"]
    assert len(system_entries) == 2
    assert all(entry["rollbackable"] is False for entry in system_entries)
    denied = await admin_client.post(
        f"/api/database/{store.id}/history/{system_entries[0]['id']}/rollback"
    )
    assert denied.status_code == 409
    assert denied.json() == {"detail": "Audit entry is not rollbackable"}


async def test_used_income_category_can_only_be_disabled(
    admin_client, category_with_item, db_session: AsyncSession
) -> None:
    response = await admin_client.delete(f"/api/admin/income-categories/{category_with_item.id}")
    assert response.status_code == 409
    response = await admin_client.patch(
        f"/api/admin/income-categories/{category_with_item.id}",
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert (await db_session.get(IncomeCategory, category_with_item.id)).is_active is False


async def test_category_briefing_sql_failure_keeps_normal_patch_response(
    admin_client,
    category_with_item,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 14, 12, tzinfo=tz)

    calls = 0

    async def sql_then_fail(service, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        await service.session.scalar(select(func.count()).select_from(DailyBriefing))
        raise RuntimeError("briefing failed after SQL")

    monkeypatch.setattr("app.api.routes.admin.datetime", FrozenDateTime)
    monkeypatch.setattr("app.services.briefing.BriefingService.regenerate", sql_then_fail)
    category_id = category_with_item.id
    store_id = category_with_item.store_id
    response = await admin_client.patch(
        f"/api/admin/income-categories/{category_id}",
        json={"include_in_total": False},
    )
    assert response.status_code == 200
    assert response.json()["id"] == category_id
    assert response.json()["include_in_total"] is False
    assert calls == 1

    persisted = await admin_client.get(
        f"/api/admin/income-categories?store_id={store_id}"
    )
    assert persisted.status_code == 200
    saved = next(item for item in persisted.json() if item["id"] == category_id)
    assert saved["include_in_total"] is False


async def test_unused_income_category_can_be_deleted_with_audit(
    admin_client, store_factory, db_session: AsyncSession
) -> None:
    store = await store_factory(name="Unused")
    category = IncomeCategory(
        store_id=store.id,
        name="Disposable",
        include_in_total=False,
        is_active=True,
        sort_order=3,
    )
    db_session.add(category)
    await db_session.flush()

    response = await admin_client.delete(f"/api/admin/income-categories/{category.id}")
    assert response.status_code == 204
    assert await db_session.get(IncomeCategory, category.id) is None
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.operation_domain == "admin",
            AuditLog.record_id == category.id,
            AuditLog.operation_type == "delete",
        )
    )
    assert audit is not None
    assert audit.before_json["name"] == "Disposable"
    assert audit.after_json is None


@pytest.mark.parametrize(
    ("method", "path", "json", "detail"),
    [
        ("patch", "/api/admin/users/999999", {"is_active": False}, "User not found"),
        ("get", "/api/admin/users/999999/stores", None, "User not found"),
        ("get", "/api/admin/users/999999/operations", None, "User not found"),
        ("patch", "/api/admin/stores/999999", {"is_active": False}, "Store not found"),
        ("get", "/api/admin/stores/999999/members", None, "Store not found"),
        ("put", "/api/admin/stores/999999/members", {"user_ids": []}, "Store not found"),
        (
            "patch",
            "/api/admin/income-categories/999999",
            {"is_active": False},
            "Category not found",
        ),
        ("delete", "/api/admin/income-categories/999999", None, "Category not found"),
    ],
)
async def test_admin_entity_lookups_return_404(admin_client, method, path, json, detail) -> None:
    response = await admin_client.request(method, path, json=json)
    assert response.status_code == 404
    assert response.json() == {"detail": detail}


async def test_member_and_category_store_references_return_404_when_absent(
    admin_client, store_factory
) -> None:
    store = await store_factory(name="Validation")
    missing_member = await admin_client.put(
        f"/api/admin/stores/{store.id}/members", json={"user_ids": [999999]}
    )
    assert missing_member.status_code == 404
    assert missing_member.json() == {"detail": "User not found"}
    missing_category_store = await admin_client.post(
        "/api/admin/income-categories",
        json={
            "store_id": 999999,
            "name": "Missing",
            "include_in_total": True,
        },
    )
    assert missing_category_store.status_code == 404
    assert missing_category_store.json() == {"detail": "Store not found"}
    missing_category_list = await admin_client.get(
        "/api/admin/income-categories", params={"store_id": 999999}
    )
    assert missing_category_list.status_code == 404
    assert missing_category_list.json() == {"detail": "Store not found"}


async def test_admin_can_list_alerts_and_task_logs_newest_first(
    admin_client, store_factory, db_session: AsyncSession
) -> None:
    store = await store_factory(name="Operations")
    earlier = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)
    later = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)
    db_session.add_all(
        [
            SystemAlert(
                store_id=store.id,
                alert_type="missing_ledger",
                level="warning",
                message="Earlier alert",
                is_resolved=False,
                created_at=earlier,
                resolved_at=None,
            ),
            SystemAlert(
                store_id=None,
                alert_type="system",
                level="error",
                message="Later alert",
                is_resolved=True,
                created_at=later,
                resolved_at=later,
            ),
            ScheduledTaskLog(
                store_id=store.id,
                task_type="scan",
                status="success",
                message="Earlier task",
                retry_count=0,
                started_at=earlier,
                finished_at=earlier,
                created_at=earlier,
            ),
            ScheduledTaskLog(
                store_id=None,
                task_type="weather",
                status="failed",
                message="Later task",
                retry_count=2,
                started_at=later,
                finished_at=None,
                created_at=later,
            ),
        ]
    )
    await db_session.flush()

    alerts = await admin_client.get("/api/admin/alerts")
    assert alerts.status_code == 200
    assert [item["message"] for item in alerts.json()] == ["Later alert", "Earlier alert"]
    assert alerts.json()[0]["resolved_at"] is not None

    task_logs = await admin_client.get("/api/admin/task-logs")
    assert task_logs.status_code == 200
    assert [item["message"] for item in task_logs.json()] == ["Later task", "Earlier task"]
    assert task_logs.json()[0]["retry_count"] == 2
