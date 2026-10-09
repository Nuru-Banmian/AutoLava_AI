import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_session, sqlite_url
from app.core.security import hash_password
from app.main import create_app

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("early_0028", [True, False])
async def test_upgrade_repairs_early_0028_without_resetting_permissions(tmp_path, early_0028):
    path = tmp_path / "scope.sqlite3"
    env = os.environ | {
        "AUTOLAVA_DATABASE_PATH": str(path),
        "AUTOLAVA_BOOTSTRAP_USERNAME": "repair-primary",
    }

    def upgrade(revision):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    upgrade("0030")
    with closing(sqlite3.connect(path)) as db:
        for ident, username, role in [
            (10, "repair-primary", "admin"),
            (20, "repair-manager", "admin"),
            (30, "repair-employee", "user"),
        ]:
            db.execute(
                "INSERT INTO users(id,auth_identity,username,password_hash,role,is_active) VALUES(?,?,?,?,?,1)",
                (ident, f"{ident:064x}", username, hash_password("synthetic-password"), role),
            )
        db.execute(
            "INSERT INTO stores(id,name,address,latitude,longitude,timezone,is_active,income_items_enabled) VALUES(40,'Synthetic','address',45,9,'Europe/Rome',1,0)"
        )
        # Empty membership represents already-revoked access; upgrading must not regrant it.
        db.commit()
    if early_0028:
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "ALTER TABLE users ADD COLUMN manager_id INTEGER REFERENCES users(id) ON DELETE RESTRICT"
            )
            db.execute("CREATE INDEX ix_users_manager_id ON users(manager_id)")
            db.execute(
                "CREATE TABLE permission_initializations(id VARCHAR(40) PRIMARY KEY, snapshot JSON NOT NULL, completed BOOLEAN NOT NULL)"
            )
            db.execute(
                "INSERT INTO permission_initializations VALUES('admin-scope-v1',?,1)",
                (
                    json.dumps(
                        {
                            "users": [{"id": 20, "username": "repair-manager", "role": "admin"}],
                            "stores": [40],
                        }
                    ),
                ),
            )
            db.execute(
                "CREATE TABLE demo_imports(id VARCHAR(40) PRIMARY KEY, version INTEGER NOT NULL, store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL)"
            )
            db.execute("UPDATE alembic_version SET version_num='0031'")
            db.execute("UPDATE users SET manager_id=20 WHERE id=30")
            db.commit()
    else:
        upgrade("0031")
        with closing(sqlite3.connect(path)) as db:
            db.execute("UPDATE permission_initializations SET completed=1")
            db.execute("UPDATE users SET manager_id=20,creator_id=10 WHERE id=30")
            db.execute("INSERT INTO employee_editors VALUES(30,20)")
            db.commit()

    with closing(sqlite3.connect(path)) as db:
        original = {}
        for (table,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
        ).fetchall():
            columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
            original[table] = (
                columns,
                db.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall(),
            )
    upgrade("head")
    upgrade("head")
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT creator_id FROM users WHERE id=30").fetchone() == (
            20 if early_0028 else 10,
        )
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0032",)
        assert db.execute("SELECT creator_id FROM users WHERE id IN (10,20)").fetchall() == [
            (None,),
            (None,),
        ]
        assert db.execute("SELECT * FROM employee_editors").fetchall() == (
            [] if early_0028 else [(30, 20)]
        )
        for table, (columns, rows) in original.items():
            selected = ",".join(f'"{c}"' for c in columns)
            assert db.execute(f'SELECT {selected} FROM "{table}" ORDER BY rowid').fetchall() == rows
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        foreign_keys = db.execute("PRAGMA foreign_key_list(users)").fetchall()
        assert any(r[3] == "creator_id" and r[6] == "SET NULL" for r in foreign_keys)

    initialized = subprocess.run(
        [sys.executable, "-m", "app.scripts.initialize_permissions"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    assert initialized.returncode == 0 and "unchanged" in initialized.stdout
    migrated_engine = create_async_engine(sqlite_url(path))
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    app = create_app()

    async def migrated_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = migrated_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            login = await client.post(
                "/api/auth/login",
                json={"username": "repair-employee", "password": "synthetic-password"},
            )
            assert login.status_code == 200
            assert (await client.get("/api/auth/me")).status_code == 200
            assert (await client.get("/api/stores/accessible")).json() == []
            assert (await client.post("/api/auth/logout")).status_code == 204
    finally:
        await migrated_engine.dispose()
