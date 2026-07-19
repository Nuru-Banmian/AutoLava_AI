import os
from pathlib import Path
import sqlite3
import subprocess
import sys

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

    with sqlite3.connect(database_path) as connection:
        tables = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name != 'alembic_version'"
            )
        }
        assert tables == EXPECTED_TABLES

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

    with sqlite3.connect(database_path) as connection:
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
