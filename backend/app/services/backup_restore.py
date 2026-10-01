"""Offline recovery drill against a disposable directory."""

import hashlib
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from app.services.sqlite_backup import _valid_backup


def verify_isolated_restore(snapshot: Path, empty_directory: Path) -> dict[str, object]:
    if not _valid_backup(snapshot, require_schema=True):
        raise ValueError("Snapshot is not a verified application database")
    if empty_directory.exists() and any(empty_directory.iterdir()):
        raise ValueError("Restore directory must be empty")
    empty_directory.mkdir(parents=True, exist_ok=True)
    restored = empty_directory / "restored.sqlite3"
    try:
        with snapshot.open("rb") as source, restored.open("xb") as target:
            shutil.copyfileobj(source, target)
        with snapshot.open("rb") as source, restored.open("rb") as target:
            if hashlib.file_digest(source, "sha256").digest() != hashlib.file_digest(target, "sha256").digest():
                raise ValueError("Restored snapshot checksum mismatch")
        with closing(sqlite3.connect(f"{restored.resolve().as_uri()}?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("Restored SQLite integrity check failed")
            version = db.execute("SELECT version_num FROM alembic_version").fetchone()
            if version is None:
                raise ValueError("Restored database has no migration version")
            tables = {
                "users": "SELECT id, username FROM users LIMIT 1",
                "stores": "SELECT id, name FROM stores LIMIT 1",
                "daily_records": "SELECT id, store_id, date FROM store_daily_records LIMIT 1",
                "income_snapshots": "SELECT id, category_name FROM daily_income_items LIMIT 1",
                "settlements": "SELECT id, company_id FROM settlement_records LIMIT 1",
            }
            readable = {name: db.execute(query).fetchone() is not None for name, query in tables.items()}
        return {"migration_version": version[0], "sample_rows_present": readable}
    except BaseException:
        restored.unlink(missing_ok=True)
        raise
