import pytest
from sqlalchemy import select

from app.models.identity import StoreMember, User


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/database/1/history"),
        ("post", "/api/database/1/history/1/rollback"),
        ("post", "/api/database/1/rollback/1"),
    ],
)
async def test_history_and_rollback_routes_do_not_exist(
    auth_client, method: str, path: str
) -> None:
    response = await auth_client.request(method, path)
    assert response.status_code == 404


async def test_database_records_route_remains_available_for_assigned_user(
    auth_client, store_factory, db_session
) -> None:
    store = await store_factory(name="Records")
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.flush()

    response = await auth_client.get(f"/api/database/{store.id}/records")

    assert response.status_code == 200
