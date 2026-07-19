import os
import re
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path


_BACKUP_NAME = re.compile(r"^autolava-(\d{8})\.sqlite3$")


def _integrity_result(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    return "" if row is None else str(row[0])


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
        with closing(sqlite3.connect(source)) as source_connection:
            with closing(sqlite3.connect(temporary_path)) as backup_connection:
                source_connection.backup(backup_connection)
        if _integrity_result(temporary_path) != "ok":
            raise RuntimeError("SQLite backup integrity check failed")
        os.replace(temporary_path, final_path)
        _prune_old_backups(destination, today)
        return final_path
    finally:
        temporary_path.unlink(missing_ok=True)
