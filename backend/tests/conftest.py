from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from decimal import Decimal

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import engine, get_session
from app.main import create_app
from app.models.base import Base
from app.models.identity import Store, User
import app.models.audit  # noqa: F401
import app.models.ledger  # noqa: F401
import app.models.operations  # noqa: F401

UserFactory = Callable[..., Awaitable[User]]
StoreFactory = Callable[..., Awaitable[Store]]


@pytest.fixture(autouse=True)
def test_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AUTOLAVA_JWT_SECRET", "test-only-jwt-secret-with-32-bytes")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if engine.dialect.name != "mysql" or engine.url.database != "autolava_test":
        raise RuntimeError("API tests require the dedicated MySQL autolava_test database")

    async with engine.connect() as connection:
        transaction = await connection.begin()
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())

        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()

    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client


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
            remember_token=None,
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
        json={"username": "authenticated", "password": "secret", "remember": False},
    )
    assert response.status_code == 200
    return client
