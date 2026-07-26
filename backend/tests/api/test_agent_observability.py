from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.model import (
    FakeModelAdapter,
    ModelAdapterError,
    ModelErrorCategory,
    ResilientModelAdapter,
)
from app.agent.service import AgentService
from app.agent.workflow import AgentTurnWorkflow
from app.core.config import get_settings
from app.models.operations import AgentSettings


async def _login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret"},
    )
    assert response.status_code == 200


class NoEvidenceCollector:
    async def collect(self, plan, context):
        del plan, context
        raise AssertionError("configuration failure must not collect evidence")


async def test_final_admin_can_read_sanitized_runs_and_alerts_after_reset(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "owner")
    get_settings.cache_clear()
    await user_factory(username="owner", password="secret", role="admin")
    store = await store_factory(name="Roma")
    store_id = store.id
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    primary = FakeModelAdapter(
        plans=[
            ModelAdapterError(
                "api-key=must-not-leak",
                category=ModelErrorCategory.INVALID_API_KEY,
            )
        ],
        provider="configured-provider",
        model="configured-model",
    )
    client._transport.app.state.agent_service = AgentService(
        AgentTurnWorkflow(
            model=ResilientModelAdapter(primary),
            evidence_collector=NoEvidenceCollector(),
        )
    )
    await _login(client, "owner")

    turn = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "本月收入是多少？"},
    )
    assert turn.status_code == 200
    assert turn.json()["route"] == "safe_failure"
    assert "must-not-leak" not in turn.text

    reset = await client.request(
        "DELETE",
        f"/api/agent/stores/{store_id}/conversation",
        json={"confirmation": "permanently_delete"},
    )
    assert reset.status_code == 204

    runs = await client.get("/api/admin/agent-observability/runs")
    alerts = await client.get("/api/admin/agent-observability/alerts")

    assert runs.status_code == 200
    assert len(runs.json()) == 1
    run = runs.json()[0]
    assert run["role"] == "final_admin"
    assert run["provider"] == "configured-provider"
    assert run["model"] == "configured-model"
    assert run["result"] == "failure"
    assert run["error_category"] == "invalid_api_key"
    assert "must-not-leak" not in runs.text
    assert alerts.status_code == 200
    assert alerts.json()[0]["alert_type"] == "configuration"
    assert alerts.json()[0]["error_category"] == "invalid_api_key"
    assert "must-not-leak" not in alerts.text


async def test_ordinary_admin_cannot_read_agent_observability(
    client: AsyncClient,
    user_factory,
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    await _login(client, "admin")

    assert (
        await client.get("/api/admin/agent-observability/runs")
    ).status_code == 403
    assert (
        await client.get("/api/admin/agent-observability/alerts")
    ).status_code == 403
