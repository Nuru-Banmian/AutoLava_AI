import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest


EXPECTED_TABLES = {
    "users",
    "stores",
    "store_members",
    "income_categories",
    "store_daily_records",
    "daily_income_items",
    "daily_briefings",
    "scheduled_task_logs",
    "system_alerts",
    "settlement_companies",
    "settlement_records",
    "settlement_audit_events",
    "agent_settings",
    "agent_conversations",
    "agent_messages",
    "agent_evidence",
    "agent_run_stats",
    "agent_alerts",
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
        assert store_columns["company_settlement_enabled"][4].strip("'") == "0"
        assert store_columns["company_settlement_enabled"][3] == 1
        assert store_columns["wash_count_enabled"][4].strip("'") == "1"
        assert store_columns["wash_count_enabled"][3] == 1
        agent_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info('agent_settings')")
        }
        assert agent_columns["enabled"][4].strip("'") == "0"
        assert agent_columns["enabled"][3] == 1
        assert agent_columns["approved_report_sha256"][3] == 0
        conversation_indexes = {
            name
            for _, name, is_unique, *_ in connection.execute(
                "PRAGMA index_list('agent_conversations')"
            )
            if is_unique
        }
        assert conversation_indexes
        message_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info('agent_messages')")
        }
        assert message_columns["action"][3] == 0
        run_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info('agent_run_stats')")
        }
        assert run_columns["run_id"][3] == 1
        alert_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info('agent_alerts')")
        }
        assert alert_columns["occurrence_count"][3] == 1
        assert alert_columns["occurrence_count"][4].strip("'") == "1"
        assert alert_columns["last_seen_at"][3] == 1

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
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
            ("operator", "hash", "admin", 1),
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
                    store_id, date, daily_revenue, income_mode, is_open, weather_edited,
                    scanned, created_by, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "2026-07-19", -1, "legacy_total", "营业", 0, 0, 1, 1),
            )

        connection.execute(
            """
            INSERT INTO store_daily_records (
                store_id, date, daily_revenue, income_mode, is_open, weather_edited,
                scanned, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "2026-07-19", 0, "legacy_total", "营业", 0, 0, 1, 1),
        )
        for day, status in ((20, "休息"), (21, "提前休息")):
            connection.execute(
                """
                INSERT INTO store_daily_records (
                    store_id, date, daily_revenue, income_mode, is_open, weather_edited,
                    scanned, created_by, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, f"2026-07-{day}", 0, "legacy_total", status, 0, 0, 1, 1),
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                """
                INSERT INTO store_daily_records (
                    store_id, date, daily_revenue, income_mode, is_open, weather_edited,
                    scanned, created_by, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0010",)
        assert (
            connection.execute("SELECT enabled FROM agent_settings WHERE id = 1").fetchone() is None
        )
        assert connection.execute("SELECT username FROM users").fetchall() == [("existing-admin",)]


def test_applied_revision_0009_preserves_existing_agent_observability(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing-agent-observability.sqlite3"
    environment = os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)}
    backend = Path(__file__).parents[1]

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0009"],
        cwd=backend,
        env=environment,
        check=True,
    )
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            """
            INSERT INTO agent_run_stats (
                user_id, store_id, role, stage, provider, model, input_tokens,
                output_tokens, result, error_category, latency_ms, estimated_cost, is_fallback
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                7,
                9,
                "final_admin",
                "answer",
                "provider",
                "model",
                120,
                30,
                "success",
                None,
                80,
                0.01,
                0,
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_alerts (
                alert_type, provider, model, error_category, message, is_resolved
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("service", "provider", "model", "provider_5xx", "脱敏告警", 0),
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
            """
            SELECT run_id, user_id, store_id, stage, provider, model, result
            FROM agent_run_stats
            """
        ).fetchone() == ("legacy-1", 7, 9, "answer", "provider", "model", "success")
        assert connection.execute(
            """
            SELECT alert_type, occurrence_count, last_seen_at = created_at, is_resolved
            FROM agent_alerts
            """
        ).fetchone() == ("service", 1, 1, 0)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0010",)
