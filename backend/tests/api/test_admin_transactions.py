import asyncio
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import database
from app.core.config import get_settings
from app.main import create_app


class WriteGate:
    def __init__(self) -> None:
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()

    async def __aenter__(self):
        self.waiting.set()
        await self.release.wait()

    async def __aexit__(self, *_args):
        return None


@pytest.mark.asyncio
async def test_migrated_management_commands_roll_back_and_recheck_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "management.sqlite3"
    backend = Path(__file__).parents[2]
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=environment,
        check=True,
        capture_output=True,
    )

    password_hash = bcrypt.hashpw(b"secret123", bcrypt.gensalt()).decode()
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO users (auth_identity, username, password_hash, role, is_active) "
            "VALUES (?, ?, ?, ?, 1)",
            ("a" * 64, "command-admin", password_hash, "admin"),
        )
        connection.execute(
            "INSERT INTO users (auth_identity, username, password_hash, role, is_active) "
            "VALUES (?, ?, ?, ?, 1)",
            ("b" * 64, "command-member", password_hash, "user"),
        )
        connection.execute(
            "INSERT INTO stores (name, address, latitude, longitude, timezone, is_active, "
            "income_items_enabled) VALUES (?, ?, ?, ?, ?, 1, 0)",
            ("Command store", "Address", 45, 9, "Europe/Rome"),
        )
        connection.commit()

    migrated_engine = create_async_engine(database.sqlite_url(database_path))
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    monkeypatch.setenv("AUTOLAVA_COOKIE_SECURE", "false")
    get_settings.cache_clear()
    app = create_app()

    async def migrated_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[database.get_session] = migrated_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            login = await client.post(
                "/api/auth/login",
                json={"username": "command-admin", "password": "secret123"},
            )
            assert login.status_code == 200
            me = await client.get("/api/auth/me")
            assert me.status_code == 200

            created = await client.put(
                "/api/admin/stores/1/income-config",
                json={
                    "expected_revision": 1,
                    "enabled": True,
                    "items": [{"name": "Wash", "include_in_total": True}],
                },
            )
            assert created.status_code == 200
            assert created.json()["revision"] == 2
            stale = await client.put(
                "/api/admin/stores/1/income-config",
                json={"expected_revision": 1, "enabled": False, "items": []},
            )
            assert stale.status_code == 409
            current = await client.get("/api/admin/stores/1/income-config")
            assert current.json()["revision"] == 2
            assert [item["name"] for item in current.json()["items"]] == ["Wash"]

            assert (
                await client.put("/api/admin/stores/1/members", json={"user_ids": [2]})
            ).status_code == 200
            rejected = await client.put("/api/admin/stores/1/members", json={"user_ids": [9999]})
            assert rejected.status_code == 404
            assert [
                member["id"] for member in (await client.get("/api/admin/stores/1/members")).json()
            ] == [2]

            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    "CREATE TRIGGER reject_member_insert BEFORE INSERT ON store_members "
                    "BEGIN SELECT RAISE(ABORT, 'injected write failure'); END"
                )
                connection.commit()
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://testserver",
                cookies=client.cookies,
            ) as failure_client:
                failed = await failure_client.put(
                    "/api/admin/stores/1/members", json={"user_ids": [2]}
                )
                assert failed.status_code == 500
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute("DROP TRIGGER reject_member_insert")
                connection.commit()
            assert [
                member["id"] for member in (await client.get("/api/admin/stores/1/members")).json()
            ] == [2]

            gate = WriteGate()
            monkeypatch.setattr(database, "SQLITE_WRITE_LOCK", gate)
            cancelled = asyncio.create_task(
                client.put("/api/admin/stores/1/members", json={"user_ids": []})
            )
            await asyncio.wait_for(gate.waiting.wait(), timeout=5)
            cancelled.cancel()
            assert isinstance(
                (await asyncio.gather(cancelled, return_exceptions=True))[0],
                asyncio.CancelledError,
            )
            gate.release.set()
            assert [
                member["id"] for member in (await client.get("/api/admin/stores/1/members")).json()
            ] == [2]

            gate = WriteGate()
            monkeypatch.setattr(database, "SQLITE_WRITE_LOCK", gate)
            revoked = asyncio.create_task(
                client.put("/api/admin/stores/1/members", json={"user_ids": []})
            )
            await asyncio.wait_for(gate.waiting.wait(), timeout=5)
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute("UPDATE users SET is_active = 0 WHERE id = 1")
                connection.commit()
            gate.release.set()
            assert (await revoked).status_code == 401

        with closing(sqlite3.connect(database_path)) as connection:
            assert connection.execute(
                "SELECT user_id FROM store_members WHERE store_id = 1"
            ).fetchall() == [(2,)]
            assert connection.execute(
                "SELECT income_config_revision FROM stores WHERE id = 1"
            ).fetchone() == (2,)
    finally:
        await migrated_engine.dispose()
