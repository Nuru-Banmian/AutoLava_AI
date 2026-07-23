import re
import sqlite3
import tempfile
from contextlib import closing

import pytest

from app.core.config import get_settings


def _create_representative_database(path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    connection.executescript(
        """
        CREATE TABLE stores (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE store_daily_records (
            id INTEGER PRIMARY KEY,
            store_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            daily_revenue INTEGER NOT NULL
        );
        INSERT INTO stores VALUES (7, 'Roma Centro');
        INSERT INTO users VALUES (8, 'configured-final-admin', 'bcrypt-hash-marker');
        INSERT INTO store_daily_records VALUES (9, 7, '2026-07-23', 456);
        """
    )
    connection.commit()
    return connection


@pytest.mark.parametrize(
    ("username", "role"),
    [
        ("ordinary-user", "user"),
        ("ordinary-admin", "admin"),
    ],
)
async def test_database_backup_rejects_everyone_except_the_final_admin(
    client,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
    username: str,
    role: str,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "configured-final-admin")
    get_settings.cache_clear()
    await user_factory(username=username, password="secret123", role=role)
    login = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert login.status_code == 200

    response = await client.get("/api/admin/database-backup")

    assert response.status_code == 403


async def test_final_admin_downloads_a_verified_snapshot_without_touching_scheduled_backups(
    client,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source = tmp_path / "live.sqlite3"
    source_connection = _create_representative_database(source)
    scheduled_backups = tmp_path / "scheduled-backups"
    scheduled_backups.mkdir()
    sentinel = scheduled_backups / "keep.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    manual_temp = tmp_path / "manual-temp"
    manual_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(manual_temp))
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "configured-final-admin")
    monkeypatch.setenv("AUTOLAVA_DATABASE_PATH", str(source))
    monkeypatch.setenv("AUTOLAVA_BACKUP_DIRECTORY", str(scheduled_backups))
    get_settings.cache_clear()
    await user_factory(
        username="configured-final-admin",
        password="secret123",
        role="admin",
    )
    login = await client.post(
        "/api/auth/login",
        json={"username": "configured-final-admin", "password": "secret123"},
    )
    assert login.status_code == 200

    try:
        response = await client.get("/api/admin/database-backup")
        assert source_connection.execute("SELECT 1").fetchone() == (1,)
    finally:
        source_connection.close()

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert re.fullmatch(
        r'attachment; filename="autolava-backup-\d{8}-\d{6}\.sqlite3"',
        disposition,
    )
    assert response.headers["cache-control"] == (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"

    downloaded = tmp_path / "downloaded.sqlite3"
    downloaded.write_bytes(response.content)
    with closing(sqlite3.connect(downloaded)) as snapshot:
        assert snapshot.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert snapshot.execute("SELECT id, name FROM stores").fetchone() == (
            7,
            "Roma Centro",
        )
        assert snapshot.execute(
            "SELECT id, username, password_hash FROM users"
        ).fetchone() == (8, "configured-final-admin", "bcrypt-hash-marker")
        assert snapshot.execute(
            "SELECT id, store_id, date, daily_revenue FROM store_daily_records"
        ).fetchone() == (9, 7, "2026-07-23", 456)

    assert list(manual_temp.iterdir()) == []
    assert list(scheduled_backups.iterdir()) == [sentinel]
    assert sentinel.read_text(encoding="utf-8") == "unchanged"


async def test_failed_snapshot_is_cleaned_without_touching_scheduled_backups(
    client,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    scheduled_backups = tmp_path / "scheduled-backups"
    scheduled_backups.mkdir()
    sentinel = scheduled_backups / "keep.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    manual_temp = tmp_path / "manual-temp"
    manual_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(manual_temp))
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "configured-final-admin")
    monkeypatch.setenv("AUTOLAVA_DATABASE_PATH", str(tmp_path / "missing.sqlite3"))
    monkeypatch.setenv("AUTOLAVA_BACKUP_DIRECTORY", str(scheduled_backups))
    get_settings.cache_clear()
    await user_factory(
        username="configured-final-admin",
        password="secret123",
        role="admin",
    )
    login = await client.post(
        "/api/auth/login",
        json={"username": "configured-final-admin", "password": "secret123"},
    )
    assert login.status_code == 200

    response = await client.get("/api/admin/database-backup")

    assert response.status_code == 500
    assert response.json() == {"detail": "Database backup could not be prepared"}
    assert list(manual_temp.iterdir()) == []
    assert list(scheduled_backups.iterdir()) == [sentinel]
