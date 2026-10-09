import os
import sqlite3
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.security import hash_password

BACKEND = Path(__file__).resolve().parents[1]


def command(env, *args, success=True):
    result = subprocess.run(
        [sys.executable, *args], cwd=BACKEND, env=env, capture_output=True, text=True
    )
    assert (result.returncode == 0) == success, result.stderr
    return result.stdout


def test_legacy_snapshot_initializes_once_and_demo_is_incremental(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    env = os.environ | {
        "AUTOLAVA_DATABASE_PATH": str(path),
        "AUTOLAVA_BOOTSTRAP_USERNAME": "primary",
        "AUTOLAVA_DEMO_DAYS": "731",
    }
    command(env, "-m", "alembic", "upgrade", "0027")
    with sqlite3.connect(path) as db:
        for ident, username, role in [
            (10, "primary", "user"),
            (20, "secondary", "admin"),
            (30, "employee", "user"),
        ]:
            db.execute(
                "INSERT INTO users(id,auth_identity,username,password_hash,role,is_active) VALUES(?,?,?,?,?,1)",
                (ident, username, username, hash_password("password123"), role),
            )
        db.execute(
            "INSERT INTO stores(id,name,address,latitude,longitude,timezone,is_active,income_items_enabled) VALUES(40,'Formal','address',45,9,'Europe/Rome',0,0)"
        )
        db.execute("INSERT INTO store_members(store_id,user_id) VALUES(40,30)")
        db.execute(
            "INSERT INTO store_daily_records(identity,revision,store_id,date,daily_revenue,income_mode,is_open,created_by,updated_by,weather_edited,weather_refresh_finished,scanned) VALUES('synthetic-original-record',1,40,'2023-05-12',321,'legacy_total','营业',30,30,0,1,0)"
        )
        original_record = db.execute(
            "SELECT * FROM store_daily_records WHERE store_id=40"
        ).fetchone()
    command(env, "-m", "alembic", "upgrade", "head")
    command(env, "-m", "app.scripts.initialize_permissions")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT manager_id FROM users WHERE id=10").fetchone() == (None,)
        assert db.execute("SELECT manager_id FROM users WHERE id=30").fetchone() == (10,)
        assert db.execute("SELECT store_id FROM store_members WHERE user_id=20").fetchall() == [
            (40,)
        ]
        db.execute("DELETE FROM store_members WHERE user_id=20")
    command(env, "-m", "app.scripts.initialize_permissions")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT store_id FROM store_members WHERE user_id=20").fetchall() == []
    first = command(env, "-m", "app.scripts.initialize_demo")
    assert "Password:" in first
    with sqlite3.connect(path) as db:
        store_id, user_id = db.execute("SELECT store_id,user_id FROM demo_imports").fetchone()
        assert store_id != 40 and user_id not in (10, 20, 30)
        assert db.execute(
            "SELECT store_id FROM store_members WHERE user_id=?", (user_id,)
        ).fetchall() == [(store_id,)]
        assert (
            db.execute(
                "SELECT COUNT(*) FROM store_daily_records WHERE store_id=?", (store_id,)
            ).fetchone()[0]
            == 731
        )
        first_day, last_day = db.execute(
            "SELECT MIN(date),MAX(date) FROM store_daily_records WHERE store_id=?", (store_id,)
        ).fetchone()
        assert (date.fromisoformat(last_day) - date.fromisoformat(first_day)).days == 730
        first_month, last_month, month_count = db.execute(
            "SELECT MIN(opening_month),MAX(opening_month),COUNT(DISTINCT opening_month) FROM settlement_records WHERE store_id=?",
            (store_id,),
        ).fetchone()
        assert first_month == first_day[:7] + "-01"
        assert last_month == last_day[:7] + "-01"
        assert month_count >= 24
        assert (
            db.execute(
                "SELECT COUNT(*) FROM settlement_records WHERE store_id=? AND status='pending' AND opening_month < date(?, 'start of month', '-1 month')",
                (store_id, last_day),
            ).fetchone()[0]
            == 0
        )
        normal_washes, early_washes = (
            db.execute(
                "SELECT AVG(wash_count) FROM store_daily_records WHERE store_id=? AND is_open=?",
                (store_id, status),
            ).fetchone()[0]
            for status in ("营业", "提前休息")
        )
        assert 0 < early_washes < normal_washes * 0.75
        for (occurred_at,) in db.execute(
            "SELECT occurred_at FROM ledger_bookkeeping_events WHERE store_id=?", (store_id,)
        ):
            local = (
                datetime.fromisoformat(occurred_at)
                .replace(tzinfo=UTC)
                .astimezone(ZoneInfo("Europe/Rome"))
            )
            assert local.hour == 18
        db.execute("UPDATE stores SET description='Experience edit' WHERE id=?", (store_id,))
    repeated = command(env | {"AUTOLAVA_DEMO_PASSWORD": "x"}, "-m", "app.scripts.initialize_demo")
    assert "Password:" not in repeated
    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT description FROM stores WHERE id=?", (store_id,)).fetchone()[0]
            == "Experience edit"
        )
        assert db.execute("SELECT COUNT(*) FROM stores").fetchone()[0] == 2
        assert (
            db.execute("SELECT * FROM store_daily_records WHERE store_id=40").fetchone()
            == original_record
        )


def test_invalid_owner_mapping_leaves_snapshot_retryable(tmp_path):
    path = tmp_path / "mapping.sqlite3"
    env = os.environ | {
        "AUTOLAVA_DATABASE_PATH": str(path),
        "AUTOLAVA_BOOTSTRAP_USERNAME": "primary",
    }
    command(env, "-m", "alembic", "upgrade", "0027")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO users(auth_identity,username,password_hash,role,is_active) VALUES('primary','primary',?,'admin',1)",
            (hash_password("password123"),),
        )
        db.execute(
            "INSERT INTO users(auth_identity,username,password_hash,role,is_active) VALUES('employee','employee',?,'user',1)",
            (hash_password("password123"),),
        )
    command(env, "-m", "alembic", "upgrade", "head")
    command(env, "-m", "app.scripts.initialize_demo", success=False)
    command(
        env | {"AUTOLAVA_BOOTSTRAP_USERNAME": "missing"},
        "-m",
        "app.scripts.initialize_permissions",
        success=False,
    )
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT completed FROM permission_initializations").fetchone() == (0,)
        assert db.execute("SELECT manager_id FROM users WHERE username='employee'").fetchone() == (
            None,
        )
        assert db.execute("SELECT COUNT(*) FROM demo_imports").fetchone() == (0,)
    command(env, "-m", "app.scripts.initialize_permissions")
    command(
        env | {"AUTOLAVA_DEMO_USERNAME": "primary"},
        "-m",
        "app.scripts.initialize_demo",
        success=False,
    )
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM stores").fetchone() == (0,)


def test_concurrent_demo_commands_create_one_import(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    env = os.environ | {
        "AUTOLAVA_DATABASE_PATH": str(path),
        "AUTOLAVA_BOOTSTRAP_USERNAME": "primary",
    }
    command(env, "-m", "alembic", "upgrade", "head")
    command(env, "-m", "app.scripts.initialize_permissions")
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "app.scripts.initialize_demo"],
            cwd=BACKEND,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    outputs = [process.communicate(timeout=30) for process in processes]
    assert [process.returncode for process in processes] == [0, 0]
    assert sum("Password:" in output for output, _ in outputs) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM demo_imports").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM stores").fetchone() == (1,)


def test_demo_conflicts_and_mid_import_failure_leave_no_partial_data(tmp_path):
    path = tmp_path / "atomic-demo.sqlite3"
    env = os.environ | {
        "AUTOLAVA_DATABASE_PATH": str(path),
        "AUTOLAVA_BOOTSTRAP_USERNAME": "primary",
    }
    command(env, "-m", "alembic", "upgrade", "head")
    command(env, "-m", "app.scripts.initialize_permissions")
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TRIGGER reject_sample BEFORE INSERT ON store_daily_records BEGIN SELECT RAISE(ABORT, 'sample failure'); END"
        )
    command(env | {"AUTOLAVA_DEMO_DAYS": "89"}, "-m", "app.scripts.initialize_demo", success=False)
    command(env, "-m", "app.scripts.initialize_demo", success=False)
    with sqlite3.connect(path) as db:
        for table in (
            "stores",
            "users",
            "income_categories",
            "store_daily_records",
            "demo_imports",
        ):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)
        db.execute("DROP TRIGGER reject_sample")
        db.execute(
            "INSERT INTO stores(name,address,latitude,longitude,timezone,is_active,income_items_enabled) VALUES('求职演示门店','address',45,9,'Europe/Rome',1,0)"
        )
    command(env, "-m", "app.scripts.initialize_demo", success=False)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone() == (0,)
        db.execute("DELETE FROM stores")
    command(
        env | {"AUTOLAVA_DEMO_STORE_NAME": " "}, "-m", "app.scripts.initialize_demo", success=False
    )
    command(env, "-m", "app.scripts.initialize_demo")
    for assignment in ("version=99", "version=1,store_id=NULL", "store_id=999999", "user_id=NULL"):
        with sqlite3.connect(path) as db:
            db.execute(f"UPDATE demo_imports SET {assignment}")
        command(env, "-m", "app.scripts.initialize_demo", success=False)
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT COUNT(*) FROM stores").fetchone() == (1,)
            assert db.execute("SELECT COUNT(*) FROM users").fetchone() == (1,)
