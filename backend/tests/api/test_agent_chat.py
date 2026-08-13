from collections.abc import Sequence
from typing import Any

import json

from httpx import AsyncClient, Response

from app.core.config import Settings
from app.services.agent_chat import AgentChatGraph, OpenAICompatibleChatModel


class FixedChatModel:
    async def complete(self, messages: Sequence[dict[str, Any]]) -> str:
        return "你好，我是 AutoLava AI。"


async def test_administrator_can_chat_through_the_agent_http_endpoint(
    client: AsyncClient,
    user_factory,
    store_factory,
) -> None:
    await user_factory(username="administrator", password="secret", role="admin")
    store = await store_factory(name="测试门店")
    login = await client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "secret"},
    )
    assert login.status_code == 200
    client._transport.app.state.agent_chat_graph = AgentChatGraph(FixedChatModel())

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"messages": [{"role": "user", "content": "你好"}]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": {"role": "assistant", "content": "你好，我是 AutoLava AI。"}
    }


async def test_agent_chat_calls_an_openai_compatible_model_through_langgraph(
    client: AsyncClient,
    user_factory,
    store_factory,
    respx_mock,
) -> None:
    await user_factory(username="administrator", password="secret", role="admin")
    store = await store_factory(name="测试门店")
    await client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "secret"},
    )
    settings = Settings(
        _env_file=None,
        agent_model_endpoint="https://model.example/v1",
        agent_model_region="eu-test-1",
        agent_model_id="basic-chat",
        agent_model_api_key="test-key",
    )
    client._transport.app.state.agent_chat_graph = AgentChatGraph(
        OpenAICompatibleChatModel(settings)
    )
    model_route = respx_mock.post("https://model.example/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={"choices": [{"message": {"content": "第二轮回答"}}]},
        )
    )

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={
            "messages": [
                {"role": "user", "content": "第一问"},
                {"role": "assistant", "content": "第一答"},
                {"role": "user", "content": "第二问"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == {
        "role": "assistant",
        "content": "第二轮回答",
    }
    request = model_route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["x-dashscope-region"] == "eu-test-1"
    assert json.loads(request.content) == {
        "model": "basic-chat",
        "messages": [
            {
                "role": "system",
                "content": "你是 AutoLava AI，一个简洁、可靠的中文助手。",
            },
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "第一答"},
            {"role": "user", "content": "第二问"},
        ],
    }


async def test_basic_agent_chat_remains_administrator_only(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post(
        "/api/agent/stores/1/messages",
        json={"messages": [{"role": "user", "content": "你好"}]},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Administrator access required"}


async def test_agent_chat_reports_missing_model_configuration_without_network(
    client: AsyncClient,
    user_factory,
    store_factory,
) -> None:
    await user_factory(username="administrator", password="secret", role="admin")
    store = await store_factory(name="测试门店")
    await client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "secret"},
    )
    client._transport.app.state.agent_chat_graph = AgentChatGraph(
        OpenAICompatibleChatModel(Settings(_env_file=None))
    )

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"messages": [{"role": "user", "content": "你好"}]},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "AI 模型尚未配置"}
