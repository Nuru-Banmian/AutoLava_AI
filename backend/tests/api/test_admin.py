import pytest
from httpx import AsyncClient


@pytest.fixture
async def admin_client(client, user_factory) -> AsyncClient:
    await user_factory(username="administrator", password="secret", role="admin")
    response = await client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "secret", "remember": False},
    )
    assert response.status_code == 200
    return client


async def test_user_operations_route_does_not_exist(admin_client, user_factory) -> None:
    user = await user_factory(username="operator", password="secret")

    response = await admin_client.get(f"/api/admin/users/{user.id}/operations")

    assert response.status_code == 404


async def test_alerts_and_task_logs_remain_admin_only(
    admin_client, auth_client
) -> None:
    login = await admin_client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "secret", "remember": False},
    )
    assert login.status_code == 200
    assert (await admin_client.get("/api/admin/alerts")).status_code == 200
    assert (await admin_client.get("/api/admin/task-logs")).status_code == 200
    login = await auth_client.post(
        "/api/auth/login",
        json={"username": "authenticated", "password": "secret", "remember": False},
    )
    assert login.status_code == 200
    assert (await auth_client.get("/api/admin/alerts")).status_code == 403
    assert (await auth_client.get("/api/admin/task-logs")).status_code == 403


async def test_store_creation_has_no_legacy_work_hours_payload(admin_client) -> None:
    response = await admin_client.post(
        "/api/admin/stores",
        json={
            "name": "No settings",
            "address": "Milan",
            "latitude": "45.000000",
            "longitude": "9.000000",
            "timezone": "Europe/Rome",
        },
    )

    assert response.status_code == 201
    assert "standard_work_hours" not in response.json()
