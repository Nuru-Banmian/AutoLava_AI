# ruff: noqa: E402

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from decimal import Decimal
import os
from pathlib import Path
import tempfile

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

_test_database_directory = tempfile.TemporaryDirectory()
os.environ["AUTOLAVA_DATABASE_PATH"] = str(
    Path(_test_database_directory.name) / "autolava-test.sqlite3"
)

from app.core.config import get_settings
from app.core.database import engine, get_session
from app.models.base import Base
from app.models.identity import Store, User
from app.services.weather import OpenMeteoProvider, WeatherService
import app.models.ledger  # noqa: F401
import app.models.operations  # noqa: F401
import app.models.settlement  # noqa: F401

UserFactory = Callable[..., Awaitable[User]]
StoreFactory = Callable[..., Awaitable[Store]]


class NoNetworkWeather:
    def __init__(self):
        self.daily_calls: list[tuple[int, object]] = []
        self.geocode_calls: list[str] = []

    async def get_daily(self, store: Store, target):
        self.daily_calls.append((store.id, target))
        return None

    async def geocode(self, query: str) -> list:
        self.geocode_calls.append(query)
        return []


@pytest.fixture(autouse=True)
def test_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AUTOLAVA_JWT_SECRET", "test-only-jwt-secret-with-32-bytes")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
async def database_schema() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()
        _test_database_directory.cleanup()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())

        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def weather_stub() -> NoNetworkWeather:
    return NoNetworkWeather()


@pytest.fixture
async def client(
    db_session: AsyncSession, weather_stub: NoNetworkWeather
) -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    app.state.weather_service = weather_stub
    app.state.open_meteo_provider = weather_stub

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client


@pytest.fixture
def open_meteo_app(client: AsyncClient) -> OpenMeteoProvider:
    provider = OpenMeteoProvider()
    app = client._transport.app
    app.state.open_meteo_provider = provider
    app.state.weather_service = WeatherService(provider)
    return provider


@pytest.fixture
def user_factory(db_session: AsyncSession) -> UserFactory:
    async def create_user(
        *,
        username: str,
        password: str,
        role: str = "user",
        is_active: bool = True,
    ) -> User:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user = User(
            username=username,
            password_hash=password_hash,
            role=role,
            is_active=is_active,
        )
        db_session.add(user)
        await db_session.flush()
        return user

    return create_user


@pytest.fixture
def store_factory(db_session: AsyncSession) -> StoreFactory:
    async def create_store(
        *,
        name: str,
        timezone: str = "Europe/Rome",
        is_active: bool = True,
    ) -> Store:
        store = Store(
            name=name,
            address=f"{name} address",
            latitude=Decimal("45.000000"),
            longitude=Decimal("9.000000"),
            timezone=timezone,
            is_active=is_active,
        )
        db_session.add(store)
        await db_session.flush()
        return store

    return create_store


@pytest.fixture
async def auth_client(client: AsyncClient, user_factory: UserFactory) -> AsyncClient:
    await user_factory(username="authenticated", password="secret")
    response = await client.post(
        "/api/auth/login",
        json={"username": "authenticated", "password": "secret"},
    )
    assert response.status_code == 200
    return client
