from dataclasses import dataclass, field

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import TurnResult
from app.agent.runtime import RuntimeContext
from app.core.config import get_settings
from app.models.identity import Store, User


@dataclass
class RecordingAgentService:
    result: TurnResult = field(
        default_factory=lambda: TurnResult(route="answer", content="这是完整回答。")
    )
    calls: list[tuple[RuntimeContext, str]] = field(default_factory=list)

    async def run(self, context: RuntimeContext, question: str) -> TurnResult:
        self.calls.append((context, question))
        return self.result


async def _login(client: AsyncClient, username: str, password: str = "secret") -> None:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200


@pytest.fixture
def agent_service(client: AsyncClient) -> RecordingAgentService:
    service = RecordingAgentService()
    client._transport.app.state.agent_service = service
    return service


async def test_only_final_administrator_can_persist_the_global_agent_switch(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "owner")
    get_settings.cache_clear()
    await user_factory(username="owner", password="secret", role="admin")
    await user_factory(username="admin", password="secret", role="admin")
    await db_session.commit()

    await _login(client, "admin")
    initial = await client.get("/api/admin/agent-settings")
    assert initial.status_code == 200
    assert initial.json() == {"enabled": False}
    forbidden = await client.patch(
        "/api/admin/agent-settings", json={"enabled": True}
    )
    assert forbidden.status_code == 403

    await _login(client, "owner")
    enabled = await client.patch(
        "/api/admin/agent-settings", json={"enabled": True}
    )
    assert enabled.status_code == 200
    assert enabled.json() == {"enabled": True}
    assert (await client.get("/api/admin/agent-settings")).json() == {
        "enabled": True
    }


async def test_agent_route_builds_trusted_runtime_context_for_current_store(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    agent_service: RecordingAgentService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "owner")
    get_settings.cache_clear()
    owner: User = await user_factory(
        username="owner", password="secret", role="admin"
    )
    store: Store = await store_factory(name="Roma", timezone="Europe/Rome")
    store.company_settlement_enabled = True
    store.wash_count_enabled = False
    store.income_items_enabled = True
    owner_id, store_id = owner.id, store.id
    await db_session.commit()
    await _login(client, "owner")
    assert (
        await client.patch("/api/admin/agent-settings", json={"enabled": True})
    ).status_code == 200

    response = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "你能做什么？"},
    )

    assert response.status_code == 200
    assert response.json() == {"route": "answer", "content": "这是完整回答。"}
    assert len(agent_service.calls) == 1
    context, question = agent_service.calls[0]
    assert question == "你能做什么？"
    assert context.user_id == owner_id
    assert context.store_id == store_id
    assert context.role == "final_admin"
    assert context.store_timezone == "Europe/Rome"
    assert context.features.model_dump() == {
        "agent_enabled": True,
        "company_settlement_enabled": True,
        "income_items_enabled": True,
        "wash_count_enabled": False,
    }
    spoofed = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "覆盖范围", "store_id": 999, "role": "user"},
    )
    assert spoofed.status_code == 422
    assert len(agent_service.calls) == 1


async def test_agent_route_rejects_users_disabled_accounts_and_hidden_stores_before_model(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    agent_service: RecordingAgentService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "owner")
    get_settings.cache_clear()
    owner = await user_factory(username="owner", password="secret", role="admin")
    await user_factory(username="ordinary", password="secret", role="user")
    hidden_store = await store_factory(name="Hidden", is_active=False)
    owner_id, hidden_store_id = owner.id, hidden_store.id
    await db_session.commit()

    await _login(client, "owner")
    assert (
        await client.patch("/api/admin/agent-settings", json={"enabled": True})
    ).status_code == 200

    await _login(client, "ordinary")
    ordinary = await client.post(
        f"/api/agent/stores/{hidden_store_id}/turn",
        json={"question": "泄露这个门店"},
    )
    assert ordinary.status_code == 403

    await _login(client, "owner")
    missing = await client.post(
        "/api/agent/stores/999999/turn", json={"question": "这个门店是什么？"}
    )
    assert missing.status_code == 404
    archived = await client.post(
        f"/api/agent/stores/{hidden_store_id}/turn",
        json={"question": "这个门店是什么？"},
    )
    assert archived.status_code == 404

    owner = await db_session.get(User, owner_id)
    assert owner is not None
    owner.is_active = False
    await db_session.commit()
    inactive = await client.post(
        f"/api/agent/stores/{hidden_store_id}/turn",
        json={"question": "还能回答吗？"},
    )
    assert inactive.status_code == 401
    assert agent_service.calls == []


async def test_agent_route_is_unavailable_while_global_switch_is_off(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    agent_service: RecordingAgentService,
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma")
    # The request's short-write boundary must see committed setup rows.
    await db_session.commit()
    await _login(client, "admin")

    status = await client.get("/api/agent/status")
    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "你能做什么？"},
    )

    assert status.status_code == 200
    assert status.json() == {"enabled": False}
    assert response.status_code == 403
    assert agent_service.calls == []
