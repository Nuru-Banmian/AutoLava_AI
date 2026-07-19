import asyncio
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.admin import patch_user
from app.core.config import get_settings
from app.core.database import (
    SQLITE_WRITE_LOCK,
    async_session_factory,
    engine,
)
from app.core.security import hash_password
from app.models.base import Base
from app.models.identity import Store, StoreMember, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.operations import DailyBriefing, ScheduledTaskLog, SystemAlert
from app.schemas.admin import UserPatch


@pytest.fixture
async def admin_client(client, user_factory) -> AsyncClient:
    await user_factory(username="administrator", password="secret", role="admin")
    response = await client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "secret"},
    )
    assert response.status_code == 200
    return client


async def test_user_operations_route_does_not_exist(admin_client, user_factory) -> None:
    user = await user_factory(username="operator", password="secret")

    response = await admin_client.get(f"/api/admin/users/{user.id}/operations")

    assert response.status_code == 404


async def test_alerts_and_task_logs_remain_admin_only(
    admin_client, auth_client
) -> None:
    login = await admin_client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "secret"},
    )
    assert login.status_code == 200
    assert (await admin_client.get("/api/admin/alerts")).status_code == 200
    assert (await admin_client.get("/api/admin/task-logs")).status_code == 200
    login = await auth_client.post(
        "/api/auth/login",
        json={"username": "authenticated", "password": "secret"},
    )
    assert login.status_code == 200
    assert (await auth_client.get("/api/admin/alerts")).status_code == 403
    assert (await auth_client.get("/api/admin/task-logs")).status_code == 403


async def test_store_creation_has_no_legacy_work_hours_payload(admin_client) -> None:
    response = await admin_client.post(
        "/api/admin/stores",
        json={
            "name": "No settings",
            "address": "Milan",
            "latitude": "45.000000",
            "longitude": "9.000000",
            "timezone": "Europe/Rome",
        },
    )

    assert response.status_code == 201
    assert "standard_work_hours" not in response.json()


async def test_admin_user_demotion_waits_for_sqlite_write_lock(
    admin_client, user_factory
) -> None:
    target = await user_factory(username="lock-target", password="secret")
    await SQLITE_WRITE_LOCK.acquire()
    try:
        mutation = asyncio.create_task(
            admin_client.patch(
                f"/api/admin/users/{target.id}",
                json={"is_active": False},
            )
        )
        try:
            response = await asyncio.wait_for(asyncio.shield(mutation), timeout=0.5)
            was_blocked = False
        except TimeoutError:
            was_blocked = True
    finally:
        SQLITE_WRITE_LOCK.release()
    if was_blocked:
        response = await mutation

    assert response.status_code == 200
    assert was_blocked is True


async def test_last_active_admin_cannot_be_deactivated(
    db_session: AsyncSession,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "inactive-owner")
    get_settings.cache_clear()
    actor = await user_factory(
        username="inactive-owner",
        password="secret",
        role="admin",
        is_active=False,
    )
    target = await user_factory(
        username="last-active",
        password="secret",
        role="admin",
    )

    with pytest.raises(HTTPException) as exc_info:
        await patch_user(
            target.id,
            UserPatch(is_active=False),
            db_session,
            actor,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "At least one active administrator is required"
    await db_session.refresh(target)
    assert target.is_active is True


async def test_owner_protection_rejects_self_management(
    client,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "protected-owner")
    get_settings.cache_clear()
    owner = await user_factory(
        username="protected-owner",
        password="secret123",
        role="admin",
    )
    login = await client.post(
        "/api/auth/login",
        json={"username": owner.username, "password": "secret123"},
    )
    assert login.status_code == 200
    owner_id = owner.id

    demoted = await client.patch(
        f"/api/admin/users/{owner_id}",
        json={"role": "user"},
    )
    deactivated = await client.patch(
        f"/api/admin/users/{owner_id}",
        json={"is_active": False},
    )
    deleted = await client.delete(f"/api/admin/users/{owner_id}")

    assert [demoted.status_code, deactivated.status_code, deleted.status_code] == [
        403,
        403,
        403,
    ]
    assert (
        await client.get("/api/admin/users")
    ).status_code == 200


@pytest.fixture
async def committed_database():
    async def clear() -> None:
        async with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                await connection.execute(table.delete())

    await clear()
    try:
        yield
    finally:
        await clear()


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/admin/users", None),
        ("post", "/api/admin/users", {"username": "denied", "password": "secret123"}),
        ("get", "/api/admin/stores", None),
        ("get", "/api/admin/income-categories?store_id=1", None),
        ("get", "/api/admin/alerts", None),
        ("get", "/api/admin/task-logs", None),
    ],
)
async def test_regular_user_is_forbidden_from_admin_management(
    auth_client, method: str, path: str, body: dict | None
) -> None:
    response = await auth_client.request(method, path, json=body)
    assert response.status_code == 403


async def test_admin_can_create_list_patch_user_and_replace_store_access(
    admin_client,
    store_factory,
    db_session: AsyncSession,
) -> None:
    alpha = await store_factory(name="Alpha")
    zulu = await store_factory(name="Zulu")

    created = await admin_client.post(
        "/api/admin/users",
        json={
            "username": "family-user",
            "password": "first-secret",
            "role": "user",
            "store_ids": [zulu.id, alpha.id, zulu.id],
        },
    )
    assert created.status_code == 201
    user_id = created.json()["id"]
    assert created.json() == {
        "id": user_id,
        "username": "family-user",
        "role": "user",
        "is_active": True,
        "store_ids": [alpha.id, zulu.id],
    }

    patched = await admin_client.patch(
        f"/api/admin/users/{user_id}",
        json={
            "password": "second-secret",
            "is_active": False,
            "store_ids": [zulu.id],
        },
    )
    listed = await admin_client.get("/api/admin/users")
    stores = await admin_client.get(f"/api/admin/users/{user_id}/stores")

    assert patched.status_code == 200
    assert patched.json()["is_active"] is False
    assert patched.json()["store_ids"] == [zulu.id]
    assert [item["username"] for item in listed.json()] == [
        "administrator",
        "family-user",
    ]
    assert [item["name"] for item in stores.json()] == ["Zulu"]
    assert list(
        await db_session.scalars(
            select(StoreMember.store_id).where(StoreMember.user_id == user_id)
        )
    ) == [zulu.id]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/admin/users", {"username": "ab", "password": "secret123"}),
        ("/api/admin/users", {"username": "x" * 81, "password": "secret123"}),
        ("/api/admin/users", {"username": "valid", "password": "short"}),
        (
            "/api/admin/users",
            {"username": "valid", "password": "secret123", "role": "manager"},
        ),
        ("/api/admin/users/1", {"password": "short"}),
        ("/api/admin/users/1", {"role": "manager"}),
    ],
)
async def test_user_validation_boundaries_return_422(
    admin_client, path: str, body: dict
) -> None:
    method = "post" if path == "/api/admin/users" else "patch"
    response = await admin_client.request(method, path, json=body)
    assert response.status_code == 422


async def test_duplicate_username_is_409_and_transaction_remains_usable(
    admin_client,
) -> None:
    body = {"username": "duplicate", "password": "secret123", "role": "user"}
    assert (await admin_client.post("/api/admin/users", json=body)).status_code == 201

    duplicate = await admin_client.post("/api/admin/users", json=body)
    listed = await admin_client.get("/api/admin/users")

    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Username already exists"}
    assert [user["username"] for user in listed.json()].count("duplicate") == 1


async def test_non_owner_cannot_grant_or_manage_admin_roles(
    admin_client,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "configured-owner")
    get_settings.cache_clear()
    owner = await user_factory(
        username="configured-owner",
        password="secret123",
        role="admin",
    )
    other_admin = await user_factory(
        username="other-admin",
        password="secret123",
        role="admin",
    )
    ordinary = await user_factory(username="ordinary", password="secret123")
    owner_id = owner.id
    other_admin_id = other_admin.id
    ordinary_id = ordinary.id

    create_admin = await admin_client.post(
        "/api/admin/users",
        json={
            "username": "forbidden-admin",
            "password": "secret123",
            "role": "admin",
        },
    )
    promote = await admin_client.patch(
        f"/api/admin/users/{ordinary_id}", json={"role": "admin"}
    )
    edit_owner = await admin_client.patch(
        f"/api/admin/users/{owner_id}", json={"password": "replacement123"}
    )
    edit_admin = await admin_client.patch(
        f"/api/admin/users/{other_admin_id}", json={"is_active": False}
    )

    assert [response.status_code for response in (
        create_admin,
        promote,
        edit_owner,
        edit_admin,
    )] == [403, 403, 403, 403]


async def test_configured_owner_can_manage_another_admin(
    client,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "configured-owner")
    get_settings.cache_clear()
    owner = await user_factory(
        username="configured-owner",
        password="secret123",
        role="admin",
    )
    target = await user_factory(
        username="managed-admin",
        password="secret123",
        role="admin",
    )
    assert (
        await client.post(
            "/api/auth/login",
            json={"username": owner.username, "password": "secret123"},
        )
    ).status_code == 200

    response = await client.patch(
        f"/api/admin/users/{target.id}", json={"role": "user"}
    )

    assert response.status_code == 200
    assert response.json()["role"] == "user"


@pytest.mark.parametrize(
    ("store_kind", "expected_status"),
    [("missing", 404), ("archived", 409)],
)
async def test_create_user_with_invalid_store_is_atomic(
    admin_client,
    store_factory,
    db_session: AsyncSession,
    store_kind: str,
    expected_status: int,
) -> None:
    store_id = (
        999_999
        if store_kind == "missing"
        else (await store_factory(name="Archived", is_active=False)).id
    )

    response = await admin_client.post(
        "/api/admin/users",
        json={
            "username": f"{store_kind}-assignment",
            "password": "secret123",
            "store_ids": [store_id],
        },
    )

    assert response.status_code == expected_status
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.username == f"{store_kind}-assignment")
        )
        == 0
    )


async def test_patch_user_invalid_store_preserves_existing_membership(
    admin_client,
    user_factory,
    store_factory,
    db_session: AsyncSession,
) -> None:
    user = await user_factory(username="atomic-member", password="secret")
    store = await store_factory(name="Existing membership")
    user_id, store_id = user.id, store.id
    db_session.add(StoreMember(store_id=store_id, user_id=user_id))
    await db_session.flush()

    response = await admin_client.patch(
        f"/api/admin/users/{user_id}",
        json={"store_ids": [999_999]},
    )

    assert response.status_code == 404
    assert list(
        await db_session.scalars(
            select(StoreMember.store_id).where(StoreMember.user_id == user_id)
        )
    ) == [store_id]


async def test_unused_user_is_deleted_with_memberships(
    admin_client,
    user_factory,
    store_factory,
    db_session: AsyncSession,
) -> None:
    user = await user_factory(username="unused-user", password="secret")
    user_id = user.id
    store = await store_factory(name="Membership")
    db_session.add(StoreMember(store_id=store.id, user_id=user_id))
    await db_session.flush()

    response = await admin_client.delete(f"/api/admin/users/{user_id}")

    assert response.status_code == 204
    assert await db_session.get(User, user_id) is None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(StoreMember)
            .where(StoreMember.user_id == user_id)
        )
        == 0
    )


@pytest.mark.parametrize("reference_field", ["created_by", "updated_by"])
async def test_referenced_user_cannot_be_deleted(
    admin_client,
    user_factory,
    store_factory,
    db_session: AsyncSession,
    reference_field: str,
) -> None:
    referenced = await user_factory(
        username=f"referenced-{reference_field}", password="secret"
    )
    other = await user_factory(username=f"other-{reference_field}", password="secret")
    store = await store_factory(name=f"User reference {reference_field}")
    record = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 10),
        daily_revenue=10,
        income_mode="legacy_total",
        is_open="营业",
        weather_edited=False,
        created_by=referenced.id if reference_field == "created_by" else other.id,
        updated_by=referenced.id if reference_field == "updated_by" else other.id,
    )
    db_session.add(record)
    await db_session.flush()

    response = await admin_client.delete(f"/api/admin/users/{referenced.id}")

    assert response.status_code == 409
    assert await db_session.get(User, referenced.id) is not None


async def test_concurrent_admin_deactivation_keeps_one_active_admin(
    committed_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "first-administrator")
    get_settings.cache_clear()
    async with async_session_factory() as setup_session:
        first = User(
            username="first-administrator",
            password_hash=hash_password("secret"),
            role="admin",
            is_active=True,
        )
        second = User(
            username="second-administrator",
            password_hash=hash_password("secret"),
            role="admin",
            is_active=True,
        )
        setup_session.add_all([first, second])
        await setup_session.commit()
        first_id, second_id = first.id, second.id

    async def deactivate(actor_id: int, target_id: int) -> int:
        async with async_session_factory() as session:
            actor = await session.get(User, actor_id)
            assert actor is not None
            try:
                await patch_user(
                    target_id,
                    UserPatch(is_active=False),
                    session,
                    actor,
                )
            except HTTPException as exc:
                return exc.status_code
            return 200

    statuses = await asyncio.gather(
        deactivate(first_id, second_id),
        deactivate(second_id, first_id),
    )

    async with async_session_factory() as verification:
        active_admins = await verification.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.is_active.is_(True))
        )
    assert sorted(statuses) == [200, 403]
    assert active_admins == 1


async def test_admin_can_create_list_patch_and_archive_stores(admin_client) -> None:
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
    alpha = await admin_client.post(
        "/api/admin/stores",
        json={
            "name": "Alpha",
            "address": "Alpha address",
            "latitude": "44.000001",
            "longitude": "8.000001",
        },
    )
    assert zulu.status_code == alpha.status_code == 201

    patched = await admin_client.patch(
        f"/api/admin/stores/{zulu.json()['id']}",
        json={
            "address": "New address",
            "timezone": "Europe/Berlin",
            "is_active": False,
        },
    )
    listed = await admin_client.get("/api/admin/stores")

    assert patched.status_code == 200
    assert patched.json()["address"] == "New address"
    assert patched.json()["timezone"] == "Europe/Berlin"
    assert patched.json()["is_active"] is False
    assert [store["name"] for store in listed.json()] == ["Alpha", "Zulu"]


@pytest.mark.parametrize(
    "body",
    [
        {
            "name": " ",
            "address": "Address",
            "latitude": 45,
            "longitude": 9,
        },
        {
            "name": "Store",
            "address": " ",
            "latitude": 45,
            "longitude": 9,
        },
        {
            "name": "Store",
            "address": "Address",
            "latitude": 91,
            "longitude": 9,
        },
        {
            "name": "Store",
            "address": "Address",
            "latitude": 45,
            "longitude": -181,
        },
        {
            "name": "Store",
            "address": "Address",
            "latitude": 45,
            "longitude": 9,
            "timezone": "Not/AZone",
        },
    ],
)
async def test_store_creation_validation_boundaries(
    admin_client, body: dict
) -> None:
    response = await admin_client.post("/api/admin/stores", json=body)
    assert response.status_code == 422


async def test_unused_store_hard_delete_removes_memberships_and_categories(
    admin_client,
    user_factory,
    store_factory,
    db_session: AsyncSession,
) -> None:
    store = await store_factory(name="Unused store")
    store_id = store.id
    user = await user_factory(username="unused-store-member", password="secret")
    db_session.add_all(
        [
            StoreMember(store_id=store_id, user_id=user.id),
            IncomeCategory(
                store_id=store_id,
                name="Cash",
                include_in_total=True,
                is_active=True,
                sort_order=0,
            ),
        ]
    )
    await db_session.flush()

    response = await admin_client.delete(f"/api/admin/stores/{store_id}")

    assert response.status_code == 204
    assert await db_session.get(Store, store_id) is None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(StoreMember)
            .where(StoreMember.store_id == store_id)
        )
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(IncomeCategory)
            .where(IncomeCategory.store_id == store_id)
        )
        == 0
    )


@pytest.mark.parametrize(
    "reference_kind",
    ["ledger", "briefing", "task", "alert"],
)
async def test_referenced_store_must_be_archived_instead_of_hard_deleted(
    admin_client,
    store_factory,
    user_factory,
    db_session: AsyncSession,
    reference_kind: str,
) -> None:
    store = await store_factory(name=f"Referenced {reference_kind}")
    owner = await user_factory(
        username=f"owner-{reference_kind}",
        password="secret",
    )
    if reference_kind == "ledger":
        reference = StoreDailyRecord(
            store_id=store.id,
            date=date(2026, 7, 15),
            daily_revenue=10,
            income_mode="legacy_total",
            is_open="营业",
            weather_edited=False,
            created_by=owner.id,
            updated_by=owner.id,
        )
    elif reference_kind == "briefing":
        reference = DailyBriefing(
            store_id=store.id,
            card_type="today",
            content="cached",
            payload={"state": "recorded"},
        )
    elif reference_kind == "task":
        reference = ScheduledTaskLog(
            store_id=store.id,
            task_type="briefing",
            status="success",
            message="done",
            retry_count=0,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
    else:
        reference = SystemAlert(
            store_id=store.id,
            alert_type="weather",
            level="warning",
            message="Provider unavailable",
            is_resolved=False,
        )
    db_session.add(reference)
    await db_session.flush()

    deleted = await admin_client.delete(f"/api/admin/stores/{store.id}")
    archived = await admin_client.patch(
        f"/api/admin/stores/{store.id}", json={"is_active": False}
    )

    assert deleted.status_code == 409
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False


async def test_store_membership_replacement_is_exact_and_deduplicated(
    admin_client,
    user_factory,
    store_factory,
    db_session: AsyncSession,
) -> None:
    removed = await user_factory(username="removed-member", password="secret")
    family = await user_factory(username="family-member", password="secret")
    store = await store_factory(name="Member replacement")
    db_session.add(StoreMember(store_id=store.id, user_id=removed.id))
    await db_session.flush()

    replaced = await admin_client.put(
        f"/api/admin/stores/{store.id}/members",
        json={"user_ids": [family.id, family.id]},
    )
    members = await admin_client.get(f"/api/admin/stores/{store.id}/members")

    assert replaced.status_code == 200
    assert replaced.json() == {"store_id": store.id, "user_ids": [family.id]}
    assert [user["username"] for user in members.json()] == ["family-member"]
    assert list(
        await db_session.scalars(
            select(StoreMember.user_id).where(StoreMember.store_id == store.id)
        )
    ) == [family.id]


async def test_invalid_store_membership_replacement_is_atomic(
    admin_client,
    user_factory,
    store_factory,
    db_session: AsyncSession,
) -> None:
    existing = await user_factory(username="existing-member", password="secret")
    administrator = await db_session.scalar(
        select(User).where(User.username == "administrator")
    )
    assert administrator is not None
    store = await store_factory(name="Atomic member replacement")
    db_session.add(StoreMember(store_id=store.id, user_id=existing.id))
    await db_session.flush()

    missing = await admin_client.put(
        f"/api/admin/stores/{store.id}/members",
        json={"user_ids": [999_999]},
    )
    admin_member = await admin_client.put(
        f"/api/admin/stores/{store.id}/members",
        json={"user_ids": [administrator.id]},
    )

    assert missing.status_code == 404
    assert admin_member.status_code == 409
    assert list(
        await db_session.scalars(
            select(StoreMember.user_id).where(StoreMember.store_id == store.id)
        )
    ) == [existing.id]


async def test_archived_store_cannot_receive_members(
    admin_client,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(username="archived-store-member", password="secret")
    store = await store_factory(name="Archived members", is_active=False)

    response = await admin_client.put(
        f"/api/admin/stores/{store.id}/members",
        json={"user_ids": [user.id]},
    )

    assert response.status_code == 409


async def test_admin_can_create_list_and_patch_current_income_categories(
    admin_client,
    store_factory,
) -> None:
    store = await store_factory(name="Current categories")
    later = await admin_client.post(
        "/api/admin/income-categories",
        json={
            "store_id": store.id,
            "name": "Later",
            "include_in_total": False,
            "sort_order": 5,
        },
    )
    first = await admin_client.post(
        "/api/admin/income-categories",
        json={
            "store_id": store.id,
            "name": "First",
            "include_in_total": True,
        },
    )
    assert later.status_code == first.status_code == 201

    listed = await admin_client.get(
        "/api/admin/income-categories", params={"store_id": store.id}
    )
    patched = await admin_client.patch(
        f"/api/admin/income-categories/{later.json()['id']}",
        json={"name": "Updated", "is_active": False, "sort_order": 1},
    )

    assert [item["name"] for item in listed.json()] == ["First", "Later"]
    assert patched.status_code == 200
    assert patched.json()["name"] == "Updated"
    assert patched.json()["is_active"] is False
    assert patched.json()["sort_order"] == 1


async def test_category_archive_restore_delete_and_reference_protection(
    admin_client,
    store_factory,
    user_factory,
    db_session: AsyncSession,
) -> None:
    store = await store_factory(name="Category lifecycle")
    owner = await user_factory(username="category-owner-admin-test", password="secret")
    used = IncomeCategory(
        store_id=store.id,
        name="Used",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    unused = IncomeCategory(
        store_id=store.id,
        name="Unused",
        include_in_total=False,
        is_active=True,
        sort_order=1,
    )
    db_session.add_all([used, unused])
    await db_session.flush()
    record = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 15),
        daily_revenue=25,
        income_mode="composed",
        is_open="营业",
        weather_edited=False,
        created_by=owner.id,
        updated_by=owner.id,
    )
    db_session.add(record)
    await db_session.flush()
    db_session.add(
        DailyIncomeItem(
            record_id=record.id,
            category_id=used.id,
            category_name="Used snapshot",
            include_in_total=True,
            sort_order=0,
            amount=25,
        )
    )
    await db_session.flush()
    used_id, unused_id = used.id, unused.id

    archived = await admin_client.post(
        f"/api/admin/income-categories/{used_id}/archive"
    )
    restored = await admin_client.post(
        f"/api/admin/income-categories/{used_id}/restore"
    )
    protected = await admin_client.delete(
        f"/api/admin/income-categories/{used_id}"
    )
    deleted = await admin_client.delete(
        f"/api/admin/income-categories/{unused_id}"
    )

    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    assert restored.json()["is_active"] is False
    assert protected.status_code == 409
    assert deleted.status_code == 204
    assert await db_session.get(IncomeCategory, unused_id) is None


async def test_category_patch_preserves_snapshot_and_refreshes_current_briefing(
    admin_client,
    store_factory,
    user_factory,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await store_factory(name="Category briefing")
    owner = await user_factory(username="category-briefing-owner", password="secret")
    category = IncomeCategory(
        store_id=store.id,
        name="Current",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add(category)
    await db_session.flush()
    local_today = datetime.now().date()
    record = StoreDailyRecord(
        store_id=store.id,
        date=local_today,
        daily_revenue=50,
        income_mode="composed",
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
        category_name="Saved snapshot",
        include_in_total=True,
        sort_order=0,
        amount=50,
    )
    db_session.add(item)
    await db_session.flush()
    calls: list[tuple[int, list[str]]] = []

    async def record_regeneration(service, store_id, card_types, **_kwargs):
        calls.append((store_id, card_types))

    monkeypatch.setattr(
        "app.services.briefing.BriefingService.regenerate",
        record_regeneration,
    )

    response = await admin_client.patch(
        f"/api/admin/income-categories/{category.id}",
        json={
            "name": "Renamed",
            "include_in_total": False,
            "sort_order": 9,
        },
    )

    assert response.status_code == 200
    assert calls == [(store.id, ["today"])]
    await db_session.refresh(record)
    await db_session.refresh(item)
    assert record.daily_revenue == 50
    assert (
        item.category_name,
        item.include_in_total,
        item.sort_order,
        item.amount,
    ) == ("Saved snapshot", True, 0, 50)


async def test_admin_geocode_and_timezone_lookup_are_normalized(
    admin_client,
    open_meteo_app,
    respx_mock,
) -> None:
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
    timezone_route = respx_mock.get(
        "https://api.open-meteo.com/v1/forecast"
    ).mock(return_value=httpx.Response(200, json={"timezone": "Europe/Rome"}))

    geocoded = await admin_client.get(
        "/api/admin/stores/geocode", params={"query": "Milano"}
    )
    timezone = await admin_client.get(
        "/api/admin/stores/timezone",
        params={"latitude": 45.46, "longitude": 9.19},
    )

    assert geocoded.status_code == 200
    assert geocoded.json() == [
        {
            "name": "Milano",
            "latitude": 45.46,
            "longitude": 9.19,
            "country": "Italia",
            "timezone": "Europe/Rome",
        }
    ]
    assert timezone.json() == {"timezone": "Europe/Rome"}
    assert timezone_route.calls[0].request.url.params["timezone"] == "auto"


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91, 9), (-91, 9), (45, 181), (45, -181)],
)
async def test_timezone_lookup_rejects_out_of_range_coordinates(
    admin_client,
    latitude: float,
    longitude: float,
) -> None:
    response = await admin_client.get(
        "/api/admin/stores/timezone",
        params={"latitude": latitude, "longitude": longitude},
    )
    assert response.status_code == 422


async def test_timezone_lookup_returns_friendly_error_when_provider_fails(
    admin_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(_latitude: float, _longitude: float) -> None:
        return None

    provider = admin_client._transport.app.state.open_meteo_provider
    monkeypatch.setattr(provider, "timezone", unavailable, raising=False)
    response = await admin_client.get(
        "/api/admin/stores/timezone",
        params={"latitude": 45, "longitude": 9},
    )
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("method", "path", "body", "detail"),
    [
        ("patch", "/api/admin/users/999999", {"is_active": False}, "User not found"),
        ("delete", "/api/admin/users/999999", None, "User not found"),
        ("get", "/api/admin/users/999999/stores", None, "User not found"),
        ("patch", "/api/admin/stores/999999", {"is_active": False}, "Store not found"),
        ("delete", "/api/admin/stores/999999", None, "Store not found"),
        ("get", "/api/admin/stores/999999/members", None, "Store not found"),
        (
            "put",
            "/api/admin/stores/999999/members",
            {"user_ids": []},
            "Store not found",
        ),
        (
            "get",
            "/api/admin/income-categories?store_id=999999",
            None,
            "Store not found",
        ),
        (
            "patch",
            "/api/admin/income-categories/999999",
            {"name": "Missing"},
            "Category not found",
        ),
        (
            "delete",
            "/api/admin/income-categories/999999",
            None,
            "Category not found",
        ),
    ],
)
async def test_admin_entity_lookups_return_404(
    admin_client,
    method: str,
    path: str,
    body: dict | None,
    detail: str,
) -> None:
    response = await admin_client.request(method, path, json=body)
    assert response.status_code == 404
    assert response.json() == {"detail": detail}


async def test_category_creation_rejects_missing_store_and_blank_name(
    admin_client,
) -> None:
    blank_name = await admin_client.post(
        "/api/admin/income-categories",
        json={"store_id": 1, "name": " ", "include_in_total": True},
    )
    missing_store = await admin_client.post(
        "/api/admin/income-categories",
        json={
            "store_id": 999_999,
            "name": "Missing",
            "include_in_total": True,
        },
    )

    assert blank_name.status_code == 422
    assert missing_store.status_code == 404


async def test_admin_lists_alerts_and_task_logs_newest_first(
    admin_client,
    store_factory,
    db_session: AsyncSession,
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
                timestamp_contract="utc_v1",
            ),
            SystemAlert(
                store_id=None,
                alert_type="system",
                level="error",
                message="Later alert",
                is_resolved=True,
                created_at=later,
                resolved_at=later,
                timestamp_contract="utc_v1",
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
                timestamp_contract="utc_v1",
            ),
            ScheduledTaskLog(
                store_id=None,
                task_type="weather_refresh",
                status="failed",
                message="Later task",
                retry_count=2,
                started_at=later,
                finished_at=None,
                created_at=later,
                timestamp_contract="utc_v1",
            ),
        ]
    )
    await db_session.flush()

    alerts = await admin_client.get("/api/admin/alerts")
    task_logs = await admin_client.get("/api/admin/task-logs")

    assert [item["message"] for item in alerts.json()] == [
        "Later alert",
        "Earlier alert",
    ]
    assert [item["message"] for item in task_logs.json()] == [
        "Later task",
        "Earlier task",
    ]
    assert alerts.json()[0]["timestamp_status"] == "utc"
    assert task_logs.json()[0]["timestamp_status"] == "utc"
    assert datetime.fromisoformat(
        alerts.json()[0]["created_at"].replace("Z", "+00:00")
    ).utcoffset() == timedelta(0)


async def test_admin_marks_legacy_operation_timestamps_unknown(
    admin_client,
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            SystemAlert(
                store_id=None,
                alert_type="legacy",
                level="warning",
                message="Legacy alert",
                is_resolved=False,
                created_at=datetime(2026, 7, 12, 8, 0),
                resolved_at=None,
            ),
            ScheduledTaskLog(
                store_id=None,
                task_type="legacy",
                status="success",
                message="Legacy task",
                retry_count=0,
                started_at=datetime(2026, 7, 12, 8, 0),
                finished_at=datetime(2026, 7, 12, 8, 5),
                created_at=datetime(2026, 7, 12, 8, 0),
            ),
        ]
    )
    await db_session.flush()

    alert = (await admin_client.get("/api/admin/alerts")).json()[0]
    task = (await admin_client.get("/api/admin/task-logs")).json()[0]

    assert alert["timestamp_status"] == "legacy_unknown"
    assert alert["created_at"] is None
    assert task["timestamp_status"] == "legacy_unknown"
    assert task["started_at"] is None
    assert task["finished_at"] is None
    assert task["created_at"] is None
