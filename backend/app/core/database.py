import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


SQLITE_WRITE_LOCK = asyncio.Lock()
_SQLITE_WRITE_ACTIVE: ContextVar[bool] = ContextVar("_SQLITE_WRITE_ACTIVE", default=False)


async def end_read_transaction(session: AsyncSession) -> None:
    """Release a dependency-opened SQLite snapshot before external or lock waits."""
    await session.rollback()


@asynccontextmanager
async def sqlite_short_write(session: AsyncSession) -> AsyncIterator[None]:
    """Run one fresh, process-serialized write transaction."""
    if _SQLITE_WRITE_ACTIVE.get():
        raise RuntimeError("Nested SQLite write transaction is not allowed")
    await end_read_transaction(session)
    async with SQLITE_WRITE_LOCK:
        active_token = _SQLITE_WRITE_ACTIVE.set(True)
        try:
            yield
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        finally:
            _SQLITE_WRITE_ACTIVE.reset(active_token)


def sqlite_url(path: Path) -> URL:
    return URL.create("sqlite+aiosqlite", database=str(path.resolve()))


def create_sqlite_engine(path: Path) -> AsyncEngine:
    """Create SQLite connections where SELECT starts a real read transaction."""
    sqlite_engine = create_async_engine(sqlite_url(path))

    @event.listens_for(sqlite_engine.sync_engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    @event.listens_for(sqlite_engine.sync_engine, "begin")
    def begin_sqlite_transaction(connection) -> None:
        connection.exec_driver_sql("BEGIN")

    return sqlite_engine


settings = get_settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
engine = create_sqlite_engine(settings.database_path)


async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
