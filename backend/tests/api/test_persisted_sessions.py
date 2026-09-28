"""Public session contract against a disposable, Alembic-migrated database."""

import asyncio
import os
import sqlite3
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import jwt
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import SQLITE_WRITE_LOCK, get_session, sqlite_url
from app.core.security import hash_password
from app.main import create_app
from app.models.identity import Store, StoreMember, User
from app.models.ledger import IncomeCategory, StoreDailyRecord


@asynccontextmanager
async def migrated_clients(tmp_path: Path):
    database = tmp_path / "sessions.sqlite3"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[2],
        env=os.environ | {"AUTOLAVA_DATABASE_PATH": str(database)},
        check=True,
        capture_output=True,
    )
    engine = create_async_engine(sqlite_url(database))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        setup.add(User(username="session-admin", password_hash=hash_password("AdminPass1"), role="admin"))
        await setup.commit()

    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as admin,
            AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as first,
            AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as second,
        ):
            yield factory, admin, first, second
    finally:
        await engine.dispose()


async def login(client: AsyncClient, username: str, password: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    return client.cookies["access_token"]


async def test_deleted_identity_never_authenticates_reused_numeric_id(tmp_path: Path) -> None:
    async with migrated_clients(tmp_path) as (_, admin, first, second):
        await login(admin, "session-admin", "AdminPass1")
        created = await admin.post(
            "/api/admin/users", json={"username": "old-user", "password": "OldPass12"}
        )
        assert created.status_code == 201
        old_id = created.json()["id"]
        old_cookie = await login(first, "old-user", "OldPass12")
        removed = await admin.delete(f"/api/admin/users/{old_id}")
        assert removed.status_code == 204
        replacement = await admin.post(
            "/api/admin/users", json={"username": "new-user", "password": "NewPass12"}
        )
        assert replacement.status_code == 201
        assert replacement.json()["id"] == old_id
        assert (await first.get("/api/auth/me")).status_code == 401
        assert (await second.get("/api/auth/me", headers={"Cookie": f"access_token={old_cookie}"})).status_code == 401
        await login(second, "new-user", "NewPass12")
        assert (await second.get("/api/auth/me")).json()["username"] == "new-user"
        legacy = jwt.encode(
            {"sub": str(old_id), "exp": 4102444800},
            get_settings().jwt_secret.get_secret_value(), algorithm="HS256",
        )
        assert (await second.get("/api/auth/me", headers={"Cookie": f"access_token={legacy}"})).status_code == 401


async def test_logout_password_change_and_admin_reset_revoke_exact_sessions(tmp_path: Path) -> None:
    async with migrated_clients(tmp_path) as (_, admin, first, second):
        await login(admin, "session-admin", "AdminPass1")
        created = await admin.post(
            "/api/admin/users", json={"username": "member", "password": "OldPass12"}
        )
        user_id = created.json()["id"]
        old_first = await login(first, "member", "OldPass12")
        old_second = await login(second, "member", "OldPass12")
        assert (await first.post("/api/auth/logout")).status_code == 204
        assert (await first.get("/api/auth/me", headers={"Cookie": f"access_token={old_first}"})).status_code == 401
        assert (await second.get("/api/auth/me")).status_code == 200
        old_first = await login(first, "member", "OldPass12")
        changed = await first.post(
            "/api/auth/password",
            json={"current_password": "OldPass12", "new_password": "NextPass12"},
        )
        assert changed.status_code == 204
        assert (await first.get("/api/auth/me")).status_code == 200
        assert (await second.get("/api/auth/me")).status_code == 401
        assert (await second.get("/api/auth/me", headers={"Cookie": f"access_token={old_first}"})).status_code == 401
        assert (await second.get("/api/auth/me", headers={"Cookie": f"access_token={old_second}"})).status_code == 401
        reset = await admin.patch(f"/api/admin/users/{user_id}", json={"password": "ResetPass12"})
        assert reset.status_code == 200
        assert (await first.get("/api/auth/me")).status_code == 401
        await login(first, "member", "ResetPass12")
        assert (await admin.patch(f"/api/admin/users/{user_id}", json={"is_active": False})).status_code == 200
        assert (await admin.patch(f"/api/admin/users/{user_id}", json={"is_active": True})).status_code == 200
        assert (await first.get("/api/auth/me")).status_code == 401


async def test_admin_store_access_removal_revokes_existing_cookie(tmp_path: Path) -> None:
    async with migrated_clients(tmp_path) as (factory, admin, first, _):
        await login(admin, "session-admin", "AdminPass1")
        async with factory() as setup:
            store = Store(
                name="Assigned store", address="Address", latitude=Decimal("45"),
                longitude=Decimal("9"), timezone="Europe/Rome",
            )
            setup.add(store)
            await setup.commit()
            store_id = store.id
        created = await admin.post(
            "/api/admin/users",
            json={"username": "member", "password": "OldPass12", "store_ids": [store_id]},
        )
        assert created.status_code == 201
        user_id = created.json()["id"]
        await login(first, "member", "OldPass12")
        assert (await first.get("/api/auth/me")).status_code == 200
        removed = await admin.patch(f"/api/admin/users/{user_id}", json={"store_ids": []})
        assert removed.status_code == 200
        assert (await first.get("/api/auth/me")).status_code == 401


async def test_waiting_write_rechecks_original_session(tmp_path: Path) -> None:
    async with migrated_clients(tmp_path) as (factory, admin, first, _):
        await login(admin, "session-admin", "AdminPass1")
        created = await admin.post(
            "/api/admin/users", json={"username": "waiting", "password": "OldPass12"}
        )
        user_id = created.json()["id"]
        await login(first, "waiting", "OldPass12")
        await SQLITE_WRITE_LOCK.acquire()
        try:
            pending = asyncio.create_task(
                first.post(
                    "/api/auth/password",
                    json={"current_password": "OldPass12", "new_password": "NewPass12"},
                )
            )
            for _ in range(1000):
                if SQLITE_WRITE_LOCK._waiters:
                    break
                await asyncio.sleep(0)
            assert not pending.done()
            async with factory() as revoke:
                user = await revoke.scalar(select(User).where(User.id == user_id))
                assert user is not None
                user.is_active = False
                await revoke.commit()
        finally:
            SQLITE_WRITE_LOCK.release()
        assert (await pending).status_code == 401
        async with factory() as verify:
            user = await verify.get(User, user_id)
            assert user is not None
            assert user.is_active is False


async def test_weather_wait_cannot_commit_after_session_revocation(tmp_path: Path) -> None:
    class PausedWeather:
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def get_daily(self, _store, _target):
            self.entered.set()
            await self.release.wait()
            return None

    async with migrated_clients(tmp_path) as (factory, admin, first, _):
        await login(admin, "session-admin", "AdminPass1")
        created = await admin.post(
            "/api/admin/users", json={"username": "ledger-user", "password": "OldPass12"}
        )
        user_id = created.json()["id"]
        async with factory() as setup:
            store = Store(
                name="Revocation store", address="Address", latitude=Decimal("45"),
                longitude=Decimal("9"), timezone="Europe/Rome", income_items_enabled=True,
            )
            setup.add(store)
            await setup.flush()
            category = IncomeCategory(
                store_id=store.id, name="Cash", include_in_total=True,
                is_active=True, sort_order=0,
            )
            setup.add_all([category, StoreMember(store_id=store.id, user_id=user_id)])
            await setup.commit()
            store_id, category_id = store.id, category.id
        await login(first, "ledger-user", "OldPass12")
        weather = PausedWeather()
        first._transport.app.state.weather_service = weather
        target = datetime.now(ZoneInfo("Europe/Rome")).date().isoformat()
        pending = asyncio.create_task(
            first.put(
                f"/api/ledger/{store_id}/{target}",
                json={"expected_identity": None, "expected_revision": None, "is_open": "营业", "items": [{"category_id": category_id, "amount": 125}]},
            )
        )
        await asyncio.wait_for(weather.entered.wait(), timeout=5)
        reset = await admin.patch(
            f"/api/admin/users/{user_id}", json={"password": "ResetPass12"}
        )
        assert reset.status_code == 200
        weather.release.set()
        response = await pending
        assert response.status_code == 401
        assert "current_record" not in response.text
        async with factory() as verify:
            assert await verify.scalar(select(func.count()).select_from(StoreDailyRecord)) == 0


async def test_existing_account_and_ledger_survive_migration_and_restart(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database)}
    migration_cwd = Path(__file__).parents[2]
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0017"],
        cwd=migration_cwd, env=environment, check=True, capture_output=True,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
            ("legacy-user", hash_password("LegacyPass12"), "user"),
        )
        connection.execute(
            "INSERT INTO stores (name, address, latitude, longitude, timezone, is_active, income_items_enabled, company_settlement_enabled, wash_count_enabled) VALUES (?, ?, ?, ?, ?, 1, 0, 0, 1)",
            ("Historic store", "Address", 45, 9, "Europe/Rome"),
        )
        connection.execute("INSERT INTO store_members (store_id, user_id) VALUES (1, 1)")
        connection.execute(
            "INSERT INTO store_daily_records (store_id, date, daily_revenue, income_mode, is_open, weather_edited, scanned, created_by, updated_by) VALUES (1, '2026-09-01', 125, 'legacy_total', '营业', 0, 0, 1, 1)"
        )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=migration_cwd, env=environment, check=True, capture_output=True,
    )
    with sqlite3.connect(database) as connection:
        identity = connection.execute("SELECT auth_identity FROM users WHERE id = 1").fetchone()
        assert identity is not None and len(identity[0]) == 64
        assert connection.execute("SELECT created_by, updated_by FROM store_daily_records").fetchone() == (1, 1)

    engine = create_async_engine(sqlite_url(database))
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def request_with_new_app(cookie: str | None = None):
        app = create_app()

        async def override_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver",
            cookies={"access_token": cookie} if cookie else None,
        ) as client:
            if cookie is None:
                cookie = await login(client, "legacy-user", "LegacyPass12")
            me = await client.get("/api/auth/me")
            record = await client.get("/api/ledger/1/2026-09-01")
            return cookie, me, record

    try:
        cookie, me, record = await request_with_new_app()
        assert me.status_code == 200
        assert record.status_code == 200
        assert record.json()["daily_revenue"] == 125
        _, restarted_me, restarted_record = await request_with_new_app(cookie)
        assert restarted_me.status_code == 200
        assert restarted_record.status_code == 200
    finally:
        await engine.dispose()
