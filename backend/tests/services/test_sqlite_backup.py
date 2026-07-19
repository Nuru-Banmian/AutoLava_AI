import sqlite3
from datetime import date

import pytest

from app.services import sqlite_backup
from app.services.sqlite_backup import backup_sqlite, has_valid_backup


def _create_database(path, value: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE snapshot_marker (value TEXT NOT NULL)")
    connection.execute("INSERT INTO snapshot_marker VALUES (?)", (value,))
    connection.commit()
    return connection


def test_online_backup_is_readable_while_source_connection_remains_open(tmp_path) -> None:
    source = tmp_path / "source.sqlite3"
    source_connection = _create_database(source, "committed")
    try:
        backup = backup_sqlite(source, tmp_path / "backups", date(2026, 7, 19))
        with sqlite3.connect(backup) as connection:
            value = connection.execute("SELECT value FROM snapshot_marker").fetchone()
        assert value == ("committed",)
        assert source_connection.execute("SELECT 1").fetchone() == (1,)
    finally:
        source_connection.close()


def test_backup_uses_dated_final_name_and_removes_temporary_file(tmp_path) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source, "snapshot").close()

    backup = backup_sqlite(source, tmp_path / "backups", date(2026, 7, 19))

    assert backup.name == "autolava-20260719.sqlite3"
    assert backup.exists()
    assert not backup.with_suffix(".sqlite3.tmp").exists()


def test_backup_checks_temporary_snapshot_integrity_before_promotion(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source, "snapshot").close()
    checked = []

    def inspect(path):
        checked.append(path)
        return "ok"

    monkeypatch.setattr(sqlite_backup, "_integrity_result", inspect)
    backup = backup_sqlite(source, tmp_path / "backups", date(2026, 7, 19))

    assert checked == [backup.with_suffix(".sqlite3.tmp")]
    assert backup.exists()


def test_failed_integrity_check_preserves_previous_same_day_backup(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source, "new").close()
    destination = tmp_path / "backups"
    destination.mkdir()
    previous = destination / "autolava-20260719.sqlite3"
    _create_database(previous, "previous").close()

    monkeypatch.setattr(sqlite_backup, "_integrity_result", lambda _path: "corrupt")
    with pytest.raises(RuntimeError, match="integrity check failed"):
        backup_sqlite(source, destination, date(2026, 7, 19))

    with sqlite3.connect(previous) as connection:
        value = connection.execute("SELECT value FROM snapshot_marker").fetchone()
    assert value == ("previous",)
    assert not previous.with_suffix(".sqlite3.tmp").exists()


def test_successful_backup_retains_three_calendar_days(tmp_path) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source, "snapshot").close()
    destination = tmp_path / "backups"
    destination.mkdir()
    for day in ("20260716", "20260717", "20260718"):
        _create_database(destination / f"autolava-{day}.sqlite3", day).close()
    unrelated = destination / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")

    backup_sqlite(source, destination, date(2026, 7, 19))

    assert sorted(path.name for path in destination.glob("*.sqlite3")) == [
        "autolava-20260717.sqlite3",
        "autolava-20260718.sqlite3",
        "autolava-20260719.sqlite3",
    ]
    assert unrelated.exists()


def test_valid_backup_requires_a_readable_integrity_checked_snapshot(tmp_path) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    today = date(2026, 7, 19)
    valid = destination / "autolava-20260719.sqlite3"
    _create_database(valid, "snapshot").close()
    assert has_valid_backup(destination, today) is True

    valid.write_bytes(b"not sqlite")
    assert has_valid_backup(destination, today) is False
