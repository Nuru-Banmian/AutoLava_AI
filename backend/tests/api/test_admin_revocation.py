import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.database import SQLITE_WRITE_LOCK, async_session_factory, engine
from app.core.security import hash_password
from app.main import create_app
from app.models.base import Base
from app.models.identity import Store, StoreMember, User
from app.models.ledger import IncomeCategory


async def _reset_database() -> None:
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())


async def _setup_admin_mutation(operation: str):
    async with async_session_factory() as session:
        actor = User(
            username="revoked-admin",
            password_hash=hash_password("secret"),
            role="admin",
            is_active=True,
        )
        target = User(
            username="mutation-target",
            password_hash=hash_password("secret"),
            role="user",
            is_active=True,
        )
        store = Store(
            name="Admin revocation",
            address="Admin revocation address",
            latitude=Decimal("45"),
            longitude=Decimal("9"),
            timezone="Europe/Berlin",
            is_active=True,
            income_items_enabled=False,
        )
        session.add_all([actor, target, store])
        await session.flush()
        category = IncomeCategory(
            store_id=store.id,
            name="Before",
            include_in_total=True,
            is_active=operation != "restore",
            sort_order=0,
            archived_at=(
                datetime.now(UTC).replace(tzinfo=None)
                if operation == "restore"
                else None
            ),
        )
        session.add(category)
        if operation == "members-replace":
            session.add(StoreMember(store_id=store.id, user_id=target.id))
        await session.commit()
        return actor.id, target.id, store.id, category.id


def _request_for(
    client: AsyncClient,
    operation: str,
    *,
    target_id: int,
    store_id: int,
    category_id: int,
):
    if operation == "replace":
        return client.put(
            f"/api/admin/stores/{store_id}/income-config",
            json={
                "enabled": True,
                "items": [
                    {
                        "category_id": category_id,
                        "name": "After",
                        "include_in_total": True,
                    }
                ],
            },
        )
    if operation in {"archive", "restore"}:
        return client.post(
            f"/api/admin/income-categories/{category_id}/{operation}"
        )
    if operation == "delete":
        return client.delete(
            f"/api/admin/income-categories/{category_id}"
        )
    if operation == "category-create":
        return client.post(
            "/api/admin/income-categories",
            json={
                "store_id": store_id,
                "name": "Created",
                "include_in_total": False,
            },
        )
    if operation == "category-patch":
        return client.patch(
            f"/api/admin/income-categories/{category_id}",
            json={"name": "After"},
        )
    if operation == "user-create":
        return client.post(
            "/api/admin/users",
            json={
                "username": "created-after-wait",
                "password": "password",
                "role": "user",
            },
        )
    if operation == "user-delete":
        return client.delete(f"/api/admin/users/{target_id}")
    if operation == "store-create":
        return client.post(
            "/api/admin/stores",
            json={
                "name": "Created after wait",
                "address": "Created after wait",
                "latitude": "45",
                "longitude": "9",
                "timezone": "Europe/Berlin",
            },
        )
    if operation == "store-patch":
        return client.patch(
            f"/api/admin/stores/{store_id}",
            json={"name": "Changed after wait"},
        )
    if operation == "store-delete":
        return client.delete(f"/api/admin/stores/{store_id}")
    if operation == "members-replace":
        return client.put(
            f"/api/admin/stores/{store_id}/members",
            json={"user_ids": []},
        )
    return client.patch(
        f"/api/admin/users/{target_id}", json={"is_active": False}
    )


@pytest.mark.parametrize(
    "operation",
    [
        "replace",
        "archive",
        "restore",
        "delete",
        "category-create",
        "category-patch",
        "user-create",
        "user-delete",
        "user-patch",
        "store-create",
        "store-patch",
        "store-delete",
        "members-replace",
    ],
)
async def test_admin_mutation_revalidates_actor_after_lock_wait(
    operation: str,
) -> None:
    await _reset_database()
    actor_id, target_id, store_id, category_id = (
        await _setup_admin_mutation(operation)
    )
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login = await client.post(
            "/api/auth/login",
            json={"username": "revoked-admin", "password": "secret"},
        )
        assert login.status_code == 200
        await SQLITE_WRITE_LOCK.acquire()
        try:
            mutation = asyncio.create_task(
                _request_for(
                    client,
                    operation,
                    target_id=target_id,
                    store_id=store_id,
                    category_id=category_id,
                )
            )
            while not SQLITE_WRITE_LOCK._waiters:
                await asyncio.sleep(0)
            async with async_session_factory() as revoke:
                actor = await revoke.get(User, actor_id)
                assert actor is not None
                if operation == "user-patch":
                    actor.is_active = False
                else:
                    actor.role = "user"
                await revoke.commit()
        finally:
            SQLITE_WRITE_LOCK.release()
        response = await mutation

    assert response.status_code == (
        401 if operation == "user-patch" else 403
    )
    async with async_session_factory() as verify:
        category = await verify.get(IncomeCategory, category_id)
        target = await verify.get(User, target_id)
        store = await verify.get(Store, store_id)
        assert category is not None
        assert target is not None
        assert store is not None
        assert target.is_active is True
        assert store.name == "Admin revocation"
        assert await verify.scalar(
            select(func.count()).select_from(Store)
        ) == 1
        assert await verify.scalar(
            select(func.count()).select_from(User)
        ) == 2
        assert category.name == "Before"
        assert store.income_items_enabled is False
        assert await verify.scalar(
            select(func.count())
            .select_from(IncomeCategory)
            .where(IncomeCategory.store_id == store_id)
        ) == 1
        if operation == "archive":
            assert category.archived_at is None
        if operation == "restore":
            assert category.archived_at is not None
        if operation == "members-replace":
            assert await verify.scalar(
                select(func.count())
                .select_from(StoreMember)
                .where(
                    StoreMember.store_id == store_id,
                    StoreMember.user_id == target_id,
                )
            ) == 1


async def test_income_config_replace_rejects_deactivated_actor_after_lock_wait() -> None:
    await _reset_database()
    actor_id, target_id, store_id, category_id = await _setup_admin_mutation(
        "replace"
    )
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login = await client.post(
            "/api/auth/login",
            json={"username": "revoked-admin", "password": "secret"},
        )
        assert login.status_code == 200
        await SQLITE_WRITE_LOCK.acquire()
        try:
            mutation = asyncio.create_task(
                _request_for(
                    client,
                    "replace",
                    target_id=target_id,
                    store_id=store_id,
                    category_id=category_id,
                )
            )
            while not SQLITE_WRITE_LOCK._waiters:
                await asyncio.sleep(0)
            async with async_session_factory() as revoke:
                actor = await revoke.get(User, actor_id)
                assert actor is not None
                actor.is_active = False
                await revoke.commit()
        finally:
            SQLITE_WRITE_LOCK.release()
        response = await mutation

    assert response.status_code == 401
    async with async_session_factory() as verify:
        store = await verify.get(Store, store_id)
        category = await verify.get(IncomeCategory, category_id)
        assert store is not None
        assert category is not None
        assert store.income_items_enabled is False
        assert category.name == "Before"
