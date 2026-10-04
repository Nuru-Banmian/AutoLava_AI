import asyncio
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from threading import Event

import pytest


@pytest.mark.asyncio
async def test_migrated_legacy_weather_remains_available_through_public_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bcrypt
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import get_session, sqlite_url
    from app.core import export_work
    from app.main import create_app

    database_path = tmp_path / "legacy-weather.sqlite3"
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)}
    backend = Path(__file__).parents[1]
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0015"], cwd=backend, env=environment, check=True)
    password_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
            ("legacy-admin", password_hash, "admin", 1),
        )
        connection.execute(
            "INSERT INTO stores (name, address, latitude, longitude, timezone, is_active, income_items_enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Legacy", "Address", 45, 9, "Europe/Rome", 1, 0),
        )
        connection.execute("INSERT INTO store_members (store_id, user_id) VALUES (1, 1)")
        connection.execute(
            "INSERT INTO store_daily_records (store_id, date, daily_revenue, income_mode, is_open, weather, weather_edited, scanned, created_by, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "2026-07-28", 940, "legacy_total", "营业", "旧版任意天气", 0, 0, 1, 1),
        )
        connection.commit()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend, env=environment, check=True)

    migrated_engine = create_async_engine(sqlite_url(database_path))
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    app = create_app()

    async def migrated_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = migrated_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.post("/api/auth/login", json={"username": "legacy-admin", "password": "secret"})).status_code == 200
        empty_window = await client.get("/api/database/1/records", params={"start": "2026-06-01", "end": "2026-06-30"})
        partial_window = await client.get("/api/database/1/records", params={"start": "2026-07-01", "end": "2026-07-31"})
        assert empty_window.status_code == partial_window.status_code == 200
        assert empty_window.json()["items"] == []
        assert [(item["date"], item["daily_revenue"]) for item in partial_window.json()["items"]] == [("2026-07-28", 940)]
        record = await client.get("/api/ledger/1/2026-07-28")
        assert record.status_code == 200
        assert record.json()["weather"] == "旧版任意天气"
        assert record.json()["weather_legacy"] is True
        assert record.json()["identity"]
        assert record.json()["revision"] == 1
        assert record.json()["config_revision"] == 1
        config = await client.get("/api/income-config/1/current")
        assert config.status_code == 200
        assert config.json()["revision"] == 1
        chart = await client.get("/api/charts/1", params={"start": "2026-07-28", "end": "2026-07-28"})
        assert chart.status_code == 200
        assert chart.json()["weather"] == [
            {"weather": "历史未规范天气", "average_revenue": 940, "operating_day_count": 1}
        ]
        entered = Event()
        release = Event()
        finished = Event()
        original_builder = export_work.build_ledger_workbook

        def blocked_builder(records, *, include_wash_count):
            entered.set()
            try:
                release.wait(timeout=10)
                return original_builder(records, include_wash_count=include_wash_count)
            finally:
                finished.set()

        monkeypatch.setattr(export_work, "build_ledger_workbook", blocked_builder)
        cancelled_export = asyncio.create_task(client.get("/api/database/1/export.xlsx"))
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as other_client:
                assert (await other_client.get("/health")).status_code == 200
            cancelled_export.cancel()
            assert isinstance((await asyncio.gather(cancelled_export, return_exceptions=True))[0], asyncio.CancelledError)
        finally:
            release.set()
        assert await asyncio.to_thread(finished.wait, 10)
        exported = await client.get("/api/database/1/export.xlsx")
        assert exported.status_code == 200
        from io import BytesIO
        from openpyxl import load_workbook
        weather_cells = list(load_workbook(BytesIO(exported.content), read_only=True)["经营记录"].values)
        assert any("历史旧值：旧版任意天气" in row for row in weather_cells)
        def failed_builder(records, *, include_wash_count):
            raise RuntimeError("test workbook failure")

        monkeypatch.setattr(export_work, "build_ledger_workbook", failed_builder)
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
            cookies=client.cookies,
        ) as failure_client:
            assert (await failure_client.get("/api/database/1/export.xlsx")).status_code == 500
    await migrated_engine.dispose()


EXPECTED_TABLES = {
    "users",
    "login_sessions",
    "stores",
    "store_members",
    "income_categories",
    "store_daily_records",
    "ledger_bookkeeping_events",
    "daily_income_items",
    "daily_briefings",
    "scheduled_task_logs",
    "system_alerts",
    "settlement_companies",
    "settlement_records",
    "settlement_audit_events",
    "agent_conversations",
    "agent_messages",
    # The replacement runtime does not map or use these archival tables. They
    # remain in the physical schema so upgrading does not destroy old chats.
    "retired_agent_system_settings",
    "retired_agent_conversations",
    "retired_agent_messages",
    "retired_agent_turns",
    "retired_agent_investigation_cards",
}


def test_blank_sqlite_file_migrates_to_final_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.sqlite3"
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)}

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[1],
        env=environment,
        check=True,
    )

    with closing(sqlite3.connect(database_path)) as connection:
        tables = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'alembic_version'"
            )
        }
        assert tables == EXPECTED_TABLES

        store_columns = {row[1]: row for row in connection.execute("PRAGMA table_info('stores')")}
        assert store_columns["income_config_revision"][4].strip("'") == "1"
        assert store_columns["income_config_revision"][3] == 1
        assert store_columns["company_settlement_enabled"][4].strip("'") == "0"
        assert store_columns["company_settlement_enabled"][3] == 1
        assert store_columns["wash_count_enabled"][4].strip("'") == "1"
        assert store_columns["wash_count_enabled"][3] == 1
        index_names = {
            name
            for _, name, is_unique, *_ in connection.execute(
                "PRAGMA index_list('store_daily_records')"
            )
            if is_unique
        }
        assert any(
            {
                column_name
                for _, _, column_name in connection.execute(f"PRAGMA index_info('{index_name}')")
            }
            == {"store_id", "date"}
            for index_name in index_names
        )
        company_index_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("uq_settlement_companies_active_store_name",),
        ).fetchone()
        assert company_index_sql is not None
        assert "UNIQUE INDEX" in company_index_sql[0]

        connection.execute(
            "INSERT INTO users (username, password_hash, role, is_active, auth_identity) VALUES (?, ?, ?, ?, ?)",
            ("admin", "hash", "admin", 1, "a" * 64),
        )
        connection.execute(
            """
            INSERT INTO stores (
                name, address, latitude, longitude, timezone, is_active,
                income_items_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Store", "Address", 45, 9, "Europe/Rome", 1, 0),
        )
        connection.execute(
            "INSERT INTO agent_conversations (user_id, store_id) VALUES (?, ?)",
            (1, 1),
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            connection.execute(
                "INSERT INTO agent_conversations (user_id, store_id) VALUES (?, ?)",
                (1, 1),
            )
        assert "WHERE is_active = 1" in company_index_sql[0]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_blank_sqlite_schema_enforces_money_and_status_constraints(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.sqlite3"
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)}

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[1],
        env=environment,
        check=True,
    )

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO users (username, password_hash, role, is_active, auth_identity) VALUES (?, ?, ?, ?, ?)",
            ("operator", "hash", "admin", 1, "b" * 64),
        )
        connection.execute(
            """
            INSERT INTO stores (
                name, address, latitude, longitude, timezone, is_active, income_items_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Store", "Address", 45, 9, "Europe/Rome", 1, 0),
        )

        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                """
                INSERT INTO store_daily_records (
                    identity, store_id, date, daily_revenue, income_mode, is_open, weather_edited,
                    scanned, created_by, updated_by
                ) VALUES (hex(randomblob(16)), ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "2026-07-19", -1, "legacy_total", "营业", 0, 0, 1, 1),
            )

        connection.execute(
            """
            INSERT INTO store_daily_records (
                identity, store_id, date, daily_revenue, income_mode, is_open, weather_edited,
                scanned, created_by, updated_by
            ) VALUES (hex(randomblob(16)), ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "2026-07-19", 0, "legacy_total", "营业", 0, 0, 1, 1),
        )
        for day, status in ((20, "休息"), (21, "提前休息")):
            connection.execute(
                """
                INSERT INTO store_daily_records (
                    identity, store_id, date, daily_revenue, income_mode, is_open, weather_edited,
                    scanned, created_by, updated_by
                ) VALUES (hex(randomblob(16)), ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, f"2026-07-{day}", 0, "legacy_total", status, 0, 0, 1, 1),
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                """
                INSERT INTO store_daily_records (
                    identity, store_id, date, daily_revenue, income_mode, is_open, weather_edited,
                    scanned, created_by, updated_by
                ) VALUES (hex(randomblob(16)), ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "2026-07-22", 0, "legacy_total", "天气停业", 0, 0, 1, 1),
            )
        connection.execute(
            """
            INSERT INTO income_categories (
                store_id, name, include_in_total, is_active, sort_order
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (1, "Wash", 1, 1, 0),
        )

        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                """
                INSERT INTO daily_income_items (
                    record_id, category_id, category_name, include_in_total, sort_order, amount
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (1, 1, "Wash", 1, 0, -1),
            )


def test_existing_store_and_ledger_survive_company_settlement_upgrade(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing.sqlite3"
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)}
    backend = Path(__file__).parents[1]

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0001"],
        cwd=backend,
        env=environment,
        check=True,
    )
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
            ("existing-admin", "hash", "admin", 1),
        )
        connection.execute(
            """
            INSERT INTO stores (
                name, address, latitude, longitude, timezone, is_active,
                income_items_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Existing", "Address", 45, 9, "Europe/Rome", 1, 0),
        )
        connection.execute(
            """
            INSERT INTO store_daily_records (
                store_id, date, daily_revenue, income_mode, is_open,
                weather_edited, scanned, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "2026-06-30", 730, "legacy_total", "营业", 0, 0, 1, 1),
        )
        connection.commit()

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=environment,
        check=True,
    )

    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute(
            "SELECT company_settlement_enabled FROM stores WHERE id = 1"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT wash_count_enabled FROM stores WHERE id = 1"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT date, daily_revenue, income_mode, is_open FROM store_daily_records WHERE id = 1"
        ).fetchone() == ("2026-06-30", 730, "legacy_total", "营业")
        assert connection.execute(
            """
            SELECT store_id, record_id, actor_id, action, timestamp_contract
            FROM ledger_bookkeeping_events
            """
        ).fetchall() == [(1, 1, 1, "created", "legacy_unknown")]
        assert connection.execute("SELECT COUNT(*) FROM stores").fetchone() == (1,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_applied_revision_0004_upgrades_without_losing_existing_data(tmp_path: Path) -> None:
    database_path = tmp_path / "existing.sqlite3"
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)}
    backend = Path(__file__).parents[1]

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0003"],
        cwd=backend,
        env=environment,
        check=True,
    )
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
            ("existing-admin", "hash", "admin", 1),
        )
        connection.execute("UPDATE alembic_version SET version_num = '0004'")
        connection.commit()

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=environment,
        check=True,
    )

    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0021",
        )
        assert connection.execute("SELECT username FROM users").fetchall() == [
            ("existing-admin",)
        ]
        tables = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {table for table in tables if table.startswith("agent_")} == {
            "agent_conversations",
            "agent_messages",
        }


def test_previous_agent_data_is_retired_without_touching_business_data(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-agent.sqlite3"
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)}
    backend = Path(__file__).parents[1]

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0015"],
        cwd=backend,
        env=environment,
        check=True,
    )
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
            ("existing-admin", "hash", "admin", 1),
        )
        connection.execute(
            """
            INSERT INTO stores (
                name, address, latitude, longitude, timezone, is_active,
                income_items_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Existing", "Address", 45, 9, "Europe/Rome", 1, 0),
        )
        connection.execute(
            """
            INSERT INTO store_daily_records (
                store_id, date, daily_revenue, income_mode, is_open, weather,
                weather_edited, scanned, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "2026-07-28", 940, "legacy_total", "营业", "旧版任意天气", 0, 0, 1, 1),
        )
        connection.execute(
            "INSERT INTO agent_system_settings (id, enabled) VALUES (?, ?)",
            (1, 1),
        )
        connection.execute(
            "INSERT INTO agent_conversations (user_id, store_id) VALUES (?, ?)",
            (1, 1),
        )
        connection.execute(
            "INSERT INTO agent_messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (1, "user", "legacy"),
        )
        connection.execute(
            "INSERT INTO agent_turns (conversation_id, user_message_id, status) VALUES (?, ?, ?)",
            (1, 1, "completed"),
        )
        connection.execute(
            """
            INSERT INTO agent_investigation_cards
                (turn_id, operation, status)
            VALUES (?, ?, ?)
            """,
            (1, "legacy-operation", "completed"),
        )
        connection.commit()

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=environment,
        check=True,
    )

    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute(
            "SELECT weather FROM store_daily_records WHERE date = '2026-07-28'"
        ).fetchone() == ("旧版任意天气",)
        tables = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {table for table in tables if table.startswith("agent_")} == {
            "agent_conversations",
            "agent_messages",
        }
        assert connection.execute("SELECT COUNT(*) FROM agent_messages").fetchone() == (0,)
        assert {
            "retired_agent_system_settings",
            "retired_agent_conversations",
            "retired_agent_messages",
            "retired_agent_turns",
            "retired_agent_investigation_cards",
        } <= tables
        assert connection.execute(
            "SELECT role, content FROM retired_agent_messages"
        ).fetchall() == [("user", "legacy")]
        assert connection.execute(
            "SELECT operation FROM retired_agent_investigation_cards"
        ).fetchall() == [("legacy-operation",)]
        assert connection.execute("SELECT username FROM users").fetchall() == [
            ("existing-admin",)
        ]
        assert connection.execute(
            "SELECT date, daily_revenue FROM store_daily_records"
        ).fetchall() == [("2026-07-28", 940)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_reused_legacy_revision_0010_upgrades_to_new_agent_schema(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-0010.sqlite3"
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)}
    backend = Path(__file__).parents[1]

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0008"],
        cwd=backend,
        env=environment,
        check=True,
    )
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
            ("existing-admin", "hash", "admin", 1),
        )
        connection.execute(
            """
            INSERT INTO stores (
                name, address, latitude, longitude, timezone, is_active,
                income_items_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Existing", "Address", 45, 9, "Europe/Rome", 1, 0),
        )
        connection.execute(
            """
            INSERT INTO store_daily_records (
                store_id, date, daily_revenue, income_mode, is_open,
                weather_edited, scanned, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "2026-07-29", 810, "legacy_total", "营业", 0, 0, 1, 1),
        )
        connection.execute(
            "INSERT INTO agent_conversations (user_id, store_id, state) VALUES (?, ?, ?)",
            (1, 1, "{}"),
        )
        connection.execute(
            "INSERT INTO agent_messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (1, "user", "legacy"),
        )
        connection.execute("UPDATE alembic_version SET version_num = '0010'")
        connection.commit()

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=environment,
        check=True,
    )

    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0021",
        )
        tables = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {table for table in tables if table.startswith("agent_")} == {
            "agent_conversations",
            "agent_messages",
        }
        assert connection.execute("SELECT username FROM users").fetchall() == [
            ("existing-admin",)
        ]
        assert connection.execute(
            "SELECT date, daily_revenue FROM store_daily_records"
        ).fetchall() == [("2026-07-29", 810)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
