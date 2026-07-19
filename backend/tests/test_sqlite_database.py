from pathlib import Path

from sqlalchemy import text

from app.core.config import Settings
from app.core.database import engine, sqlite_url


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
