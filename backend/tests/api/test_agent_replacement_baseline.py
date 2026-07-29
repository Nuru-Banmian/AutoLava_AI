from httpx import AsyncClient


async def test_legacy_agent_http_contract_is_not_registered(client: AsyncClient) -> None:
    for method, path in (
        ("GET", "/api/agent/status"),
        ("GET", "/api/agent/stores/1/conversation"),
        ("POST", "/api/agent/stores/1/turn"),
        ("GET", "/api/admin/agent-settings"),
        ("GET", "/api/admin/agent-observability"),
    ):
        response = await client.request(method, path)
        assert response.status_code == 404
