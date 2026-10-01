"""Offline recovery drill against a disposable directory."""

import hashlib
import json
import logging
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.services.sqlite_backup import _valid_backup

logger = logging.getLogger(__name__)


def _write_report(path: Path, data: dict[str, object]) -> None:
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_isolated_restore(snapshot: Path, empty_directory: Path) -> dict[str, object]:
    report = empty_directory.with_name(f"{empty_directory.name}-result.json")
    restored = empty_directory / "restored.sqlite3"
    created_restore = False
    # Invalidate the previous drill result before checking the next attempt.
    report.unlink(missing_ok=True)
    try:
        if not _valid_backup(snapshot, require_schema=True):
            raise ValueError("Snapshot is not a verified application database")
        if empty_directory.exists() and any(empty_directory.iterdir()):
            raise ValueError("Restore directory must be empty")
        empty_directory.mkdir(parents=True, exist_ok=True)
        with snapshot.open("rb") as source, restored.open("xb") as target:
            created_restore = True
            shutil.copyfileobj(source, target)
        with snapshot.open("rb") as source, restored.open("rb") as target:
            snapshot_digest = hashlib.file_digest(source, "sha256").hexdigest()
            if snapshot_digest != hashlib.file_digest(target, "sha256").hexdigest():
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
        if not all(readable.values()):
            raise ValueError("Restored database lacks representative business records")
        result = {
            "status": "local_drill_success",
            "verified_at": datetime.now(UTC).isoformat(),
            "snapshot_sha256": snapshot_digest,
            "migration_version": version[0],
            "sample_rows_present": readable,
        }
        _write_report(report, result)
        return result
    except Exception as error:
        if created_restore:
            try:
                restored.unlink(missing_ok=True)
            except OSError as cleanup_error:
                logger.error("task=isolated_restore_cleanup result=failed error_type=%s", type(cleanup_error).__name__)
        try:
            _write_report(report, {"status": "failed", "error_type": type(error).__name__})
        except Exception as report_error:
            logger.error("task=isolated_restore_report result=failed error_type=%s", type(report_error).__name__)
        raise


def restore_drill_status(report: Path | None) -> str:
    if report is None:
        return "not_verified"
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
        if data.get("status") == "failed":
            return "failed"
        if (
            data.get("status") == "local_drill_success"
            and data.get("migration_version")
            and len(data.get("snapshot_sha256", "")) == 64
            and len(data.get("sample_rows_present", {})) == 5
            and all(data["sample_rows_present"].values())
        ):
            return "local_drill_success"
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return "not_verified"
