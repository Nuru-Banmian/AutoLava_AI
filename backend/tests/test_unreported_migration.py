"""Upgrade old ledgers without changing history; use real migrated SQLite + HTTP."""

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

from app.core.database import get_session, sqlite_url
from app.main import create_app


async def test_unreported_upgrade_preserves_history_and_survives_restart(tmp_path: Path):
    database = tmp_path / "unreported.sqlite3"
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database)}
    backend = Path(__file__).parents[1]

    def migrate(target):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", target],
            cwd=backend, env=environment, capture_output=True, text=True,
        )

    old = migrate("0028")
    assert old.returncode == 0, old.stderr
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO users (username,password_hash,role,is_active,auth_identity) VALUES (?,?,?,1,lower(hex(randomblob(32))))",
                           ("migration-admin", bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode(), "admin"))
        connection.execute("INSERT INTO stores (name,address,latitude,longitude,timezone,is_active,income_items_enabled) VALUES ('Store','Address',45,9,'Europe/Rome',1,0)")
        connection.execute("INSERT INTO store_members (store_id,user_id) VALUES (1,1)")
        connection.execute("INSERT INTO income_categories (store_id,name,include_in_total,is_active,sort_order) VALUES (1,'Archived',1,0,0)")
        for identifier, status, amount, wash in [(1, "营业", 0, 0), (2, "休息", 0, None), (3, "提前休息", 240, 12)]:
            connection.execute("INSERT INTO store_daily_records (id,identity,revision,store_id,date,daily_revenue,income_mode,wash_count,is_open,weather,activity,weather_edited,scanned,created_by,updated_by) VALUES (?,?,7,1,?,?,?, ?,?,'晴','已保存事件',1,0,1,1)",
                               (identifier, f"history-{identifier}", f"2026-07-0{identifier}", amount, "composed" if identifier == 3 else "legacy_total", wash, status))
        connection.execute("INSERT INTO daily_income_items (record_id,category_id,category_name,include_in_total,sort_order,amount) VALUES (3,1,'历史名称',1,0,240)")
        connection.execute("INSERT INTO ledger_bookkeeping_events (store_id,record_id,actor_id,action) VALUES (1,3,1,'created')")
        before = connection.execute("SELECT * FROM store_daily_records ORDER BY id").fetchall()
        indexes = connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='store_daily_records'").fetchall()
        connection.commit()
    upgraded = migrate("head")
    assert upgraded.returncode == 0, upgraded.stderr
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0029",)
        assert connection.execute("SELECT * FROM store_daily_records ORDER BY id").fetchall() == before
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='store_daily_records'").fetchall() == indexes
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT category_name,amount FROM daily_income_items").fetchall() == [("历史名称", 240)]
        assert connection.execute("SELECT record_id FROM ledger_bookkeeping_events").fetchall() == [(3,)]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE store_daily_records SET daily_revenue=NULL WHERE id=1")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE store_daily_records SET is_open='未统计' WHERE id=1")
        connection.rollback()

    async def open_client(check_saved=False):
        engine = create_async_engine(sqlite_url(database))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        app = create_app()

        async def session():
            async with sessions() as current:
                yield current

        app.dependency_overrides[get_session] = session
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                assert (await client.post("/api/auth/login", json={"username": "migration-admin", "password": "secret"})).status_code == 200
                path = "/api/ledger/1/2026-07-03"
                read = await client.get(path)
                assert read.status_code == 200, read.text
                current = read.json()
                if not check_saved:
                    response = await client.put(path, json={
                        "is_open": "未统计", "confirm_clear_values": True,
                        "expected_identity": current["identity"], "expected_revision": 7,
                        "expected_config_revision": 1,
                    })
                    assert response.status_code == 200, response.text
                else:
                    assert (current["identity"], current["revision"], current["income_mode"]) == ("history-3", 8, "composed")
                    assert (current["daily_revenue"], current["wash_count"], current["items"]) == (None, None, [])
                    assert (current["weather"], current["activity"]) == ("晴", "已保存事件")
        finally:
            await engine.dispose()

    await open_client()
    await open_client(check_saved=True)
    downgrade = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0028"],
                               cwd=backend, env=environment, capture_output=True, text=True)
    assert downgrade.returncode != 0
    assert "unreported" in downgrade.stderr.lower()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0029",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
