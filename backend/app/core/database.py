import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


SQLITE_WRITE_LOCK = asyncio.Lock()


def sqlite_url(path: Path) -> URL:
    return URL.create("sqlite+aiosqlite", database=str(path.resolve()))


settings = get_settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
engine = create_async_engine(sqlite_url(settings.database_path))


@event.listens_for(engine.sync_engine, "connect")
def configure_sqlite(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
