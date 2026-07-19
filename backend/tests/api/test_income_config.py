import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import StoreMember, User
from app.models.ledger import IncomeCategory


@pytest.fixture
async def admin_client(client, user_factory) -> AsyncClient:
    await user_factory(username="config-admin", password="secret", role="admin")
    response = await client.post(
        "/api/auth/login",
        json={"username": "config-admin", "password": "secret", "remember": False},
    )
    assert response.status_code == 200
    return client


async def test_current_config_has_only_current_categories(
    auth_client, admin_client, store_factory, db_session: AsyncSession
) -> None:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    store = await store_factory(name="User current config")
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.flush()

    configured = await admin_client.put(
        f"/api/admin/stores/{store.id}/income-config",
        json={
            "enabled": True,
            "items": [
                {"name": "现金", "include_in_total": True},
                {
                    "name": "代收款",
                    "include_in_total": False,
                    "sort_order": 1,
                },
            ],
        },
    )
    assert configured.status_code == 200
    cash, agency = list(
        await db_session.scalars(
            select(IncomeCategory)
            .where(IncomeCategory.store_id == store.id)
            .order_by(IncomeCategory.sort_order)
        )
    )

    current = await auth_client.get(f"/api/income-config/{store.id}/current")
    assert current.status_code == 200
    assert current.json() == {
        "store_id": store.id,
        "enabled": True,
        "formula": "营业额 = 现金；“代收款”只记录，不计入营业额",
        "items": [
            {
                "id": cash.id,
                "store_id": store.id,
                "name": "现金",
                "include_in_total": True,
                "is_active": True,
                "sort_order": 0,
                "archived_at": None,
            },
            {
                "id": agency.id,
                "store_id": store.id,
                "name": "代收款",
                "include_in_total": False,
                "is_active": True,
                "sort_order": 1,
                "archived_at": None,
            },
        ],
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/admin/stores/1/income-config/versions"),
        ("post", "/api/admin/stores/1/income-config/versions/1/restore"),
    ],
)
async def test_income_config_version_routes_do_not_exist(
    admin_client, method: str, path: str
) -> None:
    assert (await admin_client.request(method, path)).status_code == 404
