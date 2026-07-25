import json
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


def test_blank_sqlite_schema_rejects_negative_money_values(tmp_path: Path) -> None:
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


def test_legacy_status_records_migrate_to_early_close_with_new_constraint(
    tmp_path: Path,
) -> None:
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
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
            ("migration-admin", "hash", "admin", 1),
        )
        connection.execute(
            """
            INSERT INTO stores (
                name, address, latitude, longitude, timezone, is_active,
                income_items_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Migration Store", "Address", 45, 9, "Europe/Rome", 1, 1),
        )
        connection.execute(
            """
            INSERT INTO income_categories (
                store_id, name, include_in_total, is_active, sort_order
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (1, "Cash", 1, 1, 0),
        )
        connection.execute(
            """
            INSERT INTO store_daily_records (
                store_id, date, daily_revenue, income_mode, wash_count, is_open,
                weather, activity, weather_edited, scanned, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "2026-07-20",
                730,
                "composed",
                11,
                "天气停业",
                "大雨",
                "下午提前结束",
                1,
                0,
                1,
                1,
            ),
        )
        connection.execute(
            """
            INSERT INTO daily_income_items (
                record_id, category_id, category_name, include_in_total, sort_order, amount
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, 1, "Cash", 1, 0, 730),
        )
        connection.execute(
            """
            INSERT INTO daily_briefings (store_id, card_type, content, payload)
            VALUES (?, ?, ?, ?)
            """,
            (
                1,
                "yesterday",
                "昨天因天气停业。",
                json.dumps(
                    {
                        "card_type": "yesterday",
                        "state": "weather_closed",
                        "revenue": None,
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO daily_briefings (store_id, card_type, content, payload)
            VALUES (?, ?, ?, ?)
            """,
            (
                1,
                "tomorrow",
                "明天：晴。",
                json.dumps({"card_type": "tomorrow", "state": "forecast"}),
            ),
        )
        connection.commit()

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=environment,
        check=True,
    )

    with closing(sqlite3.connect(database_path)) as connection:
        migrated = connection.execute(
            """
            SELECT date, daily_revenue, income_mode, wash_count, is_open, weather, activity
            FROM store_daily_records WHERE id = 1
            """
        ).fetchone()
        assert migrated == (
            "2026-07-20",
            730,
            "composed",
            11,
            "提前休息",
            "大雨",
            "下午提前结束",
        )
        assert connection.execute(
            """
            SELECT category_name, include_in_total, sort_order, amount
            FROM daily_income_items WHERE record_id = 1
            """
        ).fetchone() == ("Cash", 1, 0, 730)
        assert connection.execute(
            "SELECT card_type, content FROM daily_briefings ORDER BY id"
        ).fetchall() == [("tomorrow", "明天：晴。")]

        base_values = (1, "2026-07-21", 0, "legacy_total", 0, 0, 1, 1)
        for index, status in enumerate(("营业", "休息", "提前休息"), start=1):
            connection.execute(
                """
                INSERT INTO store_daily_records (
                    store_id, date, daily_revenue, income_mode, is_open,
                    weather_edited, scanned, created_by, updated_by
                ) VALUES (?, date(?, ?), ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    base_values[0],
                    base_values[1],
                    f"+{index} day",
                    base_values[2],
                    base_values[3],
                    status,
                    *base_values[4:],
                ),
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                """
                INSERT INTO store_daily_records (
                    store_id, date, daily_revenue, income_mode, is_open,
                    weather_edited, scanned, created_by, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "2026-07-25", 0, "legacy_total", "天气停业", 0, 0, 1, 1),
            )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
