import sqlite3
import subprocess
import os
import sys
import hashlib
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from app.services.backup_copy import SshBackupDestination, copy_verified_snapshot
from app.services.backup_restore import verify_isolated_restore
from app.services.sqlite_backup import backup_sqlite


def test_copy_promotes_only_after_matching_remote_checksum(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source)) as db:
        db.execute("CREATE TABLE users (id INTEGER, username TEXT, password_hash TEXT)")
        db.execute("CREATE TABLE stores (id INTEGER, name TEXT)")
        db.execute("CREATE TABLE store_daily_records (id INTEGER, store_id INTEGER, date TEXT, daily_revenue INTEGER)")
    snapshot = backup_sqlite(source, tmp_path / "local", date(2026, 10, 1))
    key = tmp_path / "key"
    known = tmp_path / "known"
    key.touch()
    known.touch()
    destination = SshBackupDestination("backup.example", "operator", "/snapshots", key, known)
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args[-1])
        if args[-1].startswith("sha256sum"):
            return subprocess.CompletedProcess(args, 0, b"0" * 64 + b"  file\n")
        return subprocess.CompletedProcess(args, 0, b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="checksum mismatch"):
        copy_verified_snapshot(snapshot, destination)
    assert commands[0].startswith("cat > ")
    assert commands[1].startswith("sha256sum ")
    assert commands[2].startswith("rm -f ")
    assert not any(command.startswith("mv ") for command in commands)


def test_copy_promotes_after_verified_transfer(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source)) as db:
        db.execute("CREATE TABLE users (id INTEGER, username TEXT, password_hash TEXT)")
        db.execute("CREATE TABLE stores (id INTEGER, name TEXT)")
        db.execute("CREATE TABLE store_daily_records (id INTEGER, store_id INTEGER, date TEXT, daily_revenue INTEGER)")
    snapshot = backup_sqlite(source, tmp_path / "local", date(2026, 10, 1))
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    key, known = tmp_path / "key", tmp_path / "known"
    key.touch()
    known.touch()
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args[-1])
        output = f"{digest}  remote\n".encode() if args[-1].startswith("sha256sum") else b""
        return subprocess.CompletedProcess(args, 0, output)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = copy_verified_snapshot(snapshot, SshBackupDestination(
        "backup.example", "operator", "/snapshots", key, known))
    assert result == digest
    assert [command.split()[0] for command in commands] == ["cat", "sha256sum", "mv"]


def test_isolated_restore_requires_empty_target_and_reads_migrated_schema(tmp_path):
    source = tmp_path / "source.sqlite3"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[2],
        env=os.environ | {"AUTOLAVA_DATABASE_PATH": str(source)},
        check=True, capture_output=True,
    )
    with closing(sqlite3.connect(source)) as db:
        db.execute("INSERT INTO users (id, auth_identity, username, password_hash, role, is_active) VALUES (1, 'sample', 'sample', 'unused', 'admin', 1)")
        db.execute("INSERT INTO stores (id, name, address, latitude, longitude, timezone, is_active, income_items_enabled) VALUES (1, 'Sample', 'Sample', 45, 9, 'Europe/Rome', 1, 1)")
        db.execute("INSERT INTO store_daily_records (id, store_id, date, daily_revenue, income_mode, is_open, weather_edited, scanned, created_by, updated_by) VALUES (1, 1, '2026-10-01', 100, 'composed', '营业', 0, 0, 1, 1)")
        db.execute("INSERT INTO income_categories (id, store_id, name, include_in_total, is_active, sort_order) VALUES (1, 1, 'Original', 1, 1, 0)")
        db.execute("INSERT INTO daily_income_items (id, record_id, category_id, category_name, include_in_total, sort_order, amount) VALUES (1, 1, 1, 'Historical', 1, 0, 100)")
        db.execute("INSERT INTO settlement_companies (id, store_id, name, normalized_name, is_active, created_by, updated_by) VALUES (1, 1, 'Company', 'company', 1, 1, 1)")
        db.execute("INSERT INTO settlement_records (id, store_id, company_id, company_name, opening_month, amount, status, revision, created_by, updated_by) VALUES (1, 1, 1, 'Company', '2026-10-01', 50, 'confirmed', 1, 1, 1)")
        db.commit()
    snapshot = backup_sqlite(source, tmp_path / "local", date(2026, 10, 1))
    result = verify_isolated_restore(snapshot, tmp_path / "restore")
    assert result["status"] == "local_drill_success"
    assert result["migration_version"]
    assert result["sample_rows_present"] == {name: True for name in (
        "users", "stores", "daily_records", "income_snapshots", "settlements")}
    report = tmp_path / "restore-result.json"
    assert '"status": "local_drill_success"' in report.read_text(encoding="utf-8")
    with closing(sqlite3.connect(tmp_path / "restore" / "restored.sqlite3")) as restored:
        assert restored.execute("SELECT daily_revenue FROM store_daily_records").fetchone() == (100,)
        assert restored.execute("SELECT category_name FROM daily_income_items").fetchone() == ("Historical",)
        assert restored.execute("SELECT amount, status FROM settlement_records").fetchone() == (50, "confirmed")
    with pytest.raises(ValueError, match="empty"):
        verify_isolated_restore(snapshot, tmp_path / "restore")
    assert '"status": "failed"' in report.read_text(encoding="utf-8")
    with closing(sqlite3.connect(source)) as db:
        db.execute("DELETE FROM settlement_records")
        db.commit()
    incomplete = backup_sqlite(source, tmp_path / "incomplete", date(2026, 10, 1))
    with pytest.raises(ValueError, match="lacks representative"):
        verify_isolated_restore(incomplete, tmp_path / "failed-restore")
    assert '"status": "failed"' in (tmp_path / "failed-restore-result.json").read_text()


def test_precheck_failure_records_result_and_report_error_preserves_cause(tmp_path, monkeypatch):
    from app.services import backup_restore

    target = tmp_path / "isolated"
    with pytest.raises(ValueError, match="not a verified"):
        verify_isolated_restore(tmp_path / "missing.sqlite3", target)
    assert '"status": "failed"' in (tmp_path / "isolated-result.json").read_text()

    def fail_report(_path, _data):
        raise OSError("report unavailable")

    stale = tmp_path / "other-result.json"
    stale.write_text('{"status":"local_drill_success"}', encoding="utf-8")
    monkeypatch.setattr(backup_restore, "_write_report", fail_report)
    with pytest.raises(ValueError, match="not a verified"):
        verify_isolated_restore(tmp_path / "missing.sqlite3", tmp_path / "other")
    assert not stale.exists()
