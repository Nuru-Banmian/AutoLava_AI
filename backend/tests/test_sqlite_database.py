import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.core.config import Settings
from app.core.database import (
    SQLITE_WRITE_LOCK,
    engine,
    sqlite_short_write,
    sqlite_url,
)
from app.models.identity import User


def test_sqlite_url_uses_aiosqlite_and_absolute_path(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "autolava.sqlite3")
    assert url.drivername == "sqlite+aiosqlite"
    assert Path(url.database or "").is_absolute()


def test_settings_use_paths_without_database_credentials(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "runtime.sqlite3",
        backup_directory=tmp_path / "backups",
    )
    assert settings.database_path.name == "runtime.sqlite3"
    assert settings.backup_directory.name == "backups"


async def test_live_connections_enable_required_pragmas() -> None:
    async with engine.connect() as connection:
        foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))
        busy_timeout = await connection.scalar(text("PRAGMA busy_timeout"))
        journal_mode = await connection.scalar(text("PRAGMA journal_mode"))
        synchronous = await connection.scalar(text("PRAGMA synchronous"))
    assert foreign_keys == 1
    assert busy_timeout == 10_000
    assert str(journal_mode).lower() == "wal"
    assert synchronous == 1


async def test_sqlite_short_write_rejects_nested_entry(db_session) -> None:
    async def enter_twice() -> None:
        async with sqlite_short_write(db_session):
            async with sqlite_short_write(db_session):
                pass

    with pytest.raises(RuntimeError, match="Nested SQLite write transaction"):
        await asyncio.wait_for(enter_twice(), timeout=0.2)


async def test_sqlite_short_write_commits_successful_work(db_session) -> None:
    async with sqlite_short_write(db_session):
        db_session.add(
            User(
                username="short-write-commit",
                password_hash="unused",
                role="user",
                is_active=True,
            )
        )

    assert await db_session.scalar(
        select(User.username).where(User.username == "short-write-commit")
    ) == "short-write-commit"


async def test_sqlite_short_write_rolls_back_exceptions(db_session) -> None:
    with pytest.raises(RuntimeError, match="stop write"):
        async with sqlite_short_write(db_session):
            db_session.add(
                User(
                    username="short-write-error",
                    password_hash="unused",
                    role="user",
                    is_active=True,
                )
            )
            await db_session.flush()
            raise RuntimeError("stop write")

    assert await db_session.scalar(
        select(User.id).where(User.username == "short-write-error")
    ) is None


async def test_sqlite_short_write_rolls_back_cancellation_and_releases_lock(
    db_session,
) -> None:
    entered = asyncio.Event()

    async def write_until_cancelled() -> None:
        async with sqlite_short_write(db_session):
            db_session.add(
                User(
                    username="short-write-cancel",
                    password_hash="unused",
                    role="user",
                    is_active=True,
                )
            )
            await db_session.flush()
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(write_until_cancelled())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert SQLITE_WRITE_LOCK.locked() is False
    assert await db_session.scalar(
        select(User.id).where(User.username == "short-write-cancel")
    ) is None
