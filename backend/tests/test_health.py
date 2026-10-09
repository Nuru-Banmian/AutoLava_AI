from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
import asyncio
from app.core.database import sqlite_url
import os
from pathlib import Path
import subprocess
import sys
import pytest


def test_health(tmp_path) -> None:
    database_path = tmp_path / "health.sqlite3"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[1],
        env=os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)},
        check=True,
        capture_output=True,
    )
    migrated_engine = create_async_engine(sqlite_url(database_path), poolclass=NullPool)
    app = create_app(session_factory=async_sessionmaker(migrated_engine, expire_on_commit=False))
    try:
        with TestClient(app) as client:
            response = client.get("/health")
    finally:
        asyncio.run(migrated_engine.dispose())
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not hasattr(app.state, "sqlite_backup_scheduler")
    assert not hasattr(app.state, "operations_retention_scheduler")


@pytest.mark.anyio
async def test_ready_checks_database_and_hides_failure(monkeypatch) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/ready")).json() == {"status": "ready"}

        def unavailable(*_args, **_kwargs):
            raise OperationalError("SELECT secret", {}, Exception("password=secret"))

        monkeypatch.setattr("app.main.engine", type("UnavailableEngine", (), {"connect": unavailable})())
        response = await client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
        assert (await client.get("/health")).json() == {"status": "ok"}


@pytest.mark.anyio
async def test_ready_uses_migrated_temporary_sqlite(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "ready.sqlite3"
    backend = Path(__file__).parents[1]
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)},
        check=True,
        capture_output=True,
    )
    migrated_engine = create_async_engine(sqlite_url(database_path))
    monkeypatch.setattr("app.main.engine", migrated_engine)
    try:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/ready")).json() == {"status": "ready"}
            empty_engine = create_async_engine(sqlite_url(tmp_path / "missing-schema.sqlite3"))
            monkeypatch.setattr("app.main.engine", empty_engine)
            try:
                assert (await client.get("/ready")).status_code == 503
                assert (await client.get("/health")).json() == {"status": "ok"}
            finally:
                await empty_engine.dispose()
    finally:
        await migrated_engine.dispose()


def test_production_exposes_one_scheduler_for_backup_and_chained_retention(
    tmp_path, monkeypatch
) -> None:
    settings = Settings(
        environment="production",
        database_path=tmp_path / "production.sqlite3",
        backup_directory=tmp_path / "backups",
        jwt_secret="production-secret-" + "x" * 32,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    app = create_app()

    assert app.state.sqlite_backup_scheduler is app.state.operations_retention_scheduler
