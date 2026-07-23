import os
import re
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path


_BACKUP_NAME = re.compile(r"^autolava-(\d{8})\.sqlite3$")
_REPRESENTATIVE_READS = (
    "SELECT id, name FROM stores ORDER BY id LIMIT 1",
    "SELECT id, username, password_hash FROM users ORDER BY id LIMIT 1",
    (
        "SELECT id, store_id, date, daily_revenue "
        "FROM store_daily_records ORDER BY id LIMIT 1"
    ),
)


def _integrity_result(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    return "" if row is None else str(row[0])


def _copy_verified_database(source: Path, snapshot: Path) -> None:
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    snapshot.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(source_uri, uri=True)) as source_connection:
            with closing(sqlite3.connect(snapshot)) as snapshot_connection:
                source_connection.backup(snapshot_connection)
        if _integrity_result(snapshot) != "ok":
            raise RuntimeError("SQLite backup integrity check failed")
    except BaseException:
        snapshot.unlink(missing_ok=True)
        raise


def create_verified_snapshot(source: Path, snapshot: Path) -> Path:
    try:
        _copy_verified_database(source, snapshot)
        with closing(sqlite3.connect(snapshot)) as snapshot_connection:
            for statement in _REPRESENTATIVE_READS:
                snapshot_connection.execute(statement).fetchone()
        return snapshot
    except BaseException:
        snapshot.unlink(missing_ok=True)
        raise


def has_valid_backup(destination: Path, today: date) -> bool:
    backup = destination / f"autolava-{today:%Y%m%d}.sqlite3"
    if not backup.is_file():
        return False
    try:
        return _integrity_result(backup) == "ok"
    except (OSError, sqlite3.Error):
        return False


def _prune_old_backups(destination: Path, today: date) -> None:
    cutoff = today - timedelta(days=2)
    for candidate in destination.glob("autolava-????????.sqlite3"):
        match = _BACKUP_NAME.fullmatch(candidate.name)
        if match is None:
            continue
        digits = match.group(1)
        try:
            backup_date = date.fromisoformat(
                f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
            )
        except ValueError:
            continue
        if backup_date < cutoff:
            candidate.unlink()


def backup_sqlite(source: Path, destination: Path, today: date) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    final_path = destination / f"autolava-{today:%Y%m%d}.sqlite3"
    temporary_path = final_path.with_suffix(".sqlite3.tmp")
    temporary_path.unlink(missing_ok=True)
    try:
        _copy_verified_database(source, temporary_path)
        os.replace(temporary_path, final_path)
        _prune_old_backups(destination, today)
        return final_path
    finally:
        temporary_path.unlink(missing_ok=True)
