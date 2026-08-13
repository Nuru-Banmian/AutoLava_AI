import pytest
from httpx import AsyncClient


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("GET", "/api/agent/stores/1"),
        ("GET", "/api/agent/stores/1/conversation"),
        ("DELETE", "/api/agent/stores/1/conversation"),
        ("GET", "/api/agent/admin/settings"),
        ("PATCH", "/api/agent/admin/settings"),
    ),
)
async def test_agent_http_contract_is_not_registered(
    client: AsyncClient,
    method: str,
    path: str,
) -> None:
    response = await client.request(method, path)

    assert response.status_code == 404
