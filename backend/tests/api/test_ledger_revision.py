"""Public HTTP regression for migrated daily-ledger revision conflicts."""

import asyncio
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import bcrypt
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_session, sqlite_url
from app.main import create_app


async def test_two_cookie_clients_create_update_and_recreate(tmp_path: Path) -> None:
    database_path = tmp_path / "ledger-revision.sqlite3"
    backend = Path(__file__).parents[2]
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)},
        check=True,
        capture_output=True,
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO users (username, password_hash, role, is_active, auth_identity) VALUES (?, ?, ?, ?, ?)",
            ("operator", bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode(), "admin", 1, "a" * 64),
        )
        connection.execute(
            "INSERT INTO stores (name, address, latitude, longitude, timezone, is_active, income_items_enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Store", "Address", 45, 9, "Europe/Rome", 1, 0),
        )
        connection.execute("INSERT INTO store_members (store_id, user_id) VALUES (1, 1)")

    engine = create_async_engine(sqlite_url(database_path))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()

    class NoWeather:
        async def get_daily(self, *_args):
            return None

    app.state.weather_service = NoWeather()

    async def session_override():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    target = datetime.now(ZoneInfo("Europe/Rome")).date().isoformat()
    path = f"/api/ledger/1/{target}"

    def body(amount: int, identity: str | None = None, revision: int | None = None) -> dict:
        return {
            "expected_identity": identity,
            "expected_revision": revision,
            "is_open": "营业",
            "daily_revenue": amount,
            "items": [],
        }

    try:
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as first,
            AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as second,
        ):
            for client in (first, second):
                assert (
                    await client.post(
                        "/api/auth/login", json={"username": "operator", "password": "secret"}
                    )
                ).status_code == 200

            assert (
                await first.put(path, json={"is_open": "营业", "daily_revenue": 10, "items": []})
            ).status_code == 428
            assert "重新加载" in (await first.request("DELETE", path)).text
            empty_form = (await first.get(f"{path}/form-config")).json()
            assert empty_form["identity"] is None and empty_form["revision"] is None

            gate = asyncio.Event()

            async def create(client: AsyncClient, amount: int):
                await gate.wait()
                return await client.put(path, json=body(amount))

            tasks = [
                asyncio.create_task(create(first, 100)),
                asyncio.create_task(create(second, 200)),
            ]
            gate.set()
            created = await asyncio.gather(*tasks)
            assert sorted(response.status_code for response in created) == [201, 409]
            assert (
                created[0].json().get("detail", {}).get("code") == "ledger_revision_conflict"
                or created[1].json().get("detail", {}).get("code") == "ledger_revision_conflict"
            )

            old = (await first.get(path)).json()
            assert old["identity"] and old["revision"] == 1
            existing_form = (await first.get(f"{path}/form-config")).json()
            assert (existing_form["identity"], existing_form["revision"]) == (old["identity"], 1)
            changed = await first.put(path, json=body(300, old["identity"], old["revision"]))
            assert changed.status_code == 200
            assert changed.json()["revision"] == 2
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "UPDATE store_daily_records SET temperature_max = 26.1 WHERE store_id = 1"
                )
            stale = await second.put(path, json=body(400, old["identity"], old["revision"]))
            assert stale.status_code == 409
            assert stale.json()["detail"]["current"]["daily_revenue"] == 300
            assert stale.json()["detail"]["current"]["temperature_max"] == 26.1
            with sqlite3.connect(database_path) as connection:
                assert (
                    connection.execute("SELECT COUNT(*) FROM ledger_bookkeeping_events").fetchone()[
                        0
                    ]
                    == 2
                )

            deleted = await first.request(
                "DELETE", path, json={"expected_identity": old["identity"], "expected_revision": 2}
            )
            assert deleted.status_code == 204
            rebuilt = await second.put(path, json=body(500))
            assert rebuilt.status_code == 201
            assert rebuilt.json()["id"] == old["id"]
            assert rebuilt.json()["identity"] != old["identity"]
            stale_delete = await first.request(
                "DELETE", path, json={"expected_identity": old["identity"], "expected_revision": 2}
            )
            assert stale_delete.status_code == 409
            assert stale_delete.json()["detail"]["current"]["daily_revenue"] == 500
            assert (await first.get(path)).json()["daily_revenue"] == 500
            with sqlite3.connect(database_path) as connection:
                connection.execute("UPDATE users SET is_active = 0 WHERE username = 'operator'")
            denied = await first.put(path, json=body(600, rebuilt.json()["identity"], 1))
            assert denied.status_code == 401
            assert "current" not in denied.text
    finally:
        await engine.dispose()
