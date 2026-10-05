"""Verify upgrading existing business data and reading descriptions after restart via HTTP."""

import asyncio
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_session, sqlite_url
from app.core.security import hash_password
from app.main import create_app


async def test_old_store_migrates_and_description_survives_restart(tmp_path: Path):
    database = tmp_path / "description.sqlite3"
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database)}
    backend = Path(__file__).parents[2]
    for revision in ("0021", "head"):
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision],
                       cwd=backend, env=environment, check=True, capture_output=True)
        if revision == "0021":
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "INSERT INTO users (auth_identity, username, password_hash, role, is_active) "
                    "VALUES (?, 'old-admin', ?, 'admin', 1)",
                    (secrets.token_hex(32), hash_password("password123")),
                )
                connection.execute(
                    "INSERT INTO stores (name, address, latitude, longitude, timezone, "
                    "is_active, income_items_enabled) VALUES ('旧门店', 'Roma', 45, 9, 'Europe/Rome', 1, 0)"
                )
                connection.execute(
                    "INSERT INTO store_daily_records (identity, store_id, date, daily_revenue, income_mode, "
                    "is_open, weather, weather_edited, scanned, created_by, updated_by) "
                    "VALUES ('old-record-identity', 1, '2026-07-28', 940, 'legacy_total', '营业', '晴', 1, 0, 1, 1)"
                )

    for restart in (False, True):
        migrated_engine = create_async_engine(sqlite_url(database))
        sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
        app = create_app()

        async def session_dependency():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = session_dependency
        try:
            async with AsyncClient(transport=ASGITransport(app), base_url="http://testserver") as client:
                assert (await client.post("/api/auth/login", json={
                    "username": "old-admin", "password": "password123",
                })).status_code == 200
                store = next(item for item in (await client.get("/api/admin/stores")).json()
                             if item["id"] == 1)
                assert store["description"] == ("维修门店\n附近居民" if restart else "")
                assert store["description_revision"] == (2 if restart else 1)
                assert (await client.get("/api/ledger/1/2026-07-28")).json()["daily_revenue"] == 940
                if not restart:
                    saved = await client.patch("/api/admin/stores/1", json={
                        "description": "维修门店\n附近居民", "expected_description_revision": 1,
                    })
                    assert saved.status_code == 200
                    second = (await client.post("/api/admin/stores", json={
                        "name": "另一个门店", "address": "Roma", "latitude": 45, "longitude": 9,
                    })).json()
                    assert second["description"] == ""
                else:
                    async with AsyncClient(transport=ASGITransport(app), base_url="http://testserver") as other:
                        await other.post("/api/auth/login", json={
                            "username": "old-admin", "password": "password123",
                        })
                        results = await asyncio.gather(
                            client.patch("/api/admin/stores/1", json={
                                "description": "甲草稿", "expected_description_revision": 2,
                            }),
                            other.patch("/api/admin/stores/1", json={
                                "description": "乙草稿", "expected_description_revision": 2,
                            }),
                        )
                        assert sorted(response.status_code for response in results) == [200, 409]
                        winner = next(response.json() for response in results if response.status_code == 200)
                        loser = next(response.json() for response in results if response.status_code == 409)
                        assert loser["detail"]["latest"]["description"] == winner["description"]
                        assert winner["description_revision"] == 3
                        latest = next(item for item in (await client.get("/api/admin/stores")).json()
                                      if item["id"] == 1)
                        assert latest["description"] == winner["description"]
                        assert latest["description_revision"] == 3
        finally:
            await migrated_engine.dispose()
