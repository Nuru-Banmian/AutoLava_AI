from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.conversation import AgentRunResult
from app.agent.contracts import TurnResult
from app.agent.model import (
    FakeModelAdapter,
    ModelAttempt,
    ModelAdapterError,
    ModelErrorCategory,
    ResilientModelAdapter,
)
from app.agent.service import AgentService
from app.agent.workflow import AgentTurnWorkflow
from app.core.config import get_settings
from app.models.agent import AgentAlert
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


async def _setup_owner_agent(
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "owner")
    get_settings.cache_clear()
    await user_factory(username="owner", password="secret", role="admin")
    store = await store_factory(name="Roma")
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    return store


async def test_final_admin_can_read_sanitized_runs_and_alerts_after_reset(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await _setup_owner_agent(db_session, user_factory, store_factory, monkeypatch)
    store_id = store.id
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
    assert run["run_id"]
    assert run["role"] == "final_admin"
    assert run["stage"] == "plan"
    assert run["provider"] == "configured-provider"
    assert run["model"] == "configured-model"
    assert run["input_tokens"] is None
    assert run["output_tokens"] is None
    assert run["result"] == "failure"
    assert run["error_category"] == "invalid_api_key"
    assert run["latency_ms"] >= 0
    assert run["estimated_cost"] is None
    assert run["is_fallback"] is False
    assert "user_id" not in run
    assert "store_id" not in run
    assert "must-not-leak" not in runs.text
    assert alerts.status_code == 200
    assert alerts.json()[0]["alert_type"] == "configuration"
    assert alerts.json()[0]["error_category"] == "invalid_api_key"
    assert alerts.json()[0]["occurrence_count"] == 1
    assert alerts.json()[0]["last_seen_at"]
    assert "must-not-leak" not in alerts.text


async def test_ordinary_admin_cannot_read_agent_observability(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    alert = AgentAlert(
        alert_type="service",
        provider="provider",
        model="model",
        error_category="timeout",
        message="模型服务持续不可用，请检查供应商状态。",
        is_resolved=False,
    )
    db_session.add(alert)
    await db_session.commit()
    await _login(client, "admin")

    assert (await client.get("/api/admin/agent-observability/runs")).status_code == 403
    assert (await client.get("/api/admin/agent-observability/alerts")).status_code == 403
    assert (
        await client.patch(
            f"/api/admin/agent-observability/alerts/{alert.id}",
            json={"status": "resolved"},
        )
    ).status_code == 403


async def test_repeated_alerts_are_deduplicated_and_final_admin_can_resolve_them(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await _setup_owner_agent(db_session, user_factory, store_factory, monkeypatch)
    primary = FakeModelAdapter(
        plans=[
            ModelAdapterError(
                "api-key=first-secret",
                category=ModelErrorCategory.INVALID_API_KEY,
            ),
            ModelAdapterError(
                "api-key=second-secret",
                category=ModelErrorCategory.INVALID_API_KEY,
            ),
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

    for question in ("第一次调查", "第二次调查"):
        response = await client.post(
            f"/api/agent/stores/{store.id}/turn",
            json={"question": question},
        )
        assert response.status_code == 200

    alerts = await client.get("/api/admin/agent-observability/alerts")
    assert alerts.status_code == 200
    assert len(alerts.json()) == 1
    alert = alerts.json()[0]
    assert alert["occurrence_count"] == 2
    assert alert["is_resolved"] is False
    assert "secret" not in alerts.text

    resolved = await client.patch(
        f"/api/admin/agent-observability/alerts/{alert['id']}",
        json={"status": "resolved"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["is_resolved"] is True
    assert resolved.json()["resolved_at"]


async def test_unrecovered_provider_outage_creates_one_sanitized_service_alert(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await _setup_owner_agent(db_session, user_factory, store_factory, monkeypatch)
    primary = FakeModelAdapter(
        plans=[
            ModelAdapterError(
                "upstream=https://secret-provider.example",
                category=ModelErrorCategory.PROVIDER_5XX,
            ),
            ModelAdapterError(
                "upstream=https://secret-provider.example",
                category=ModelErrorCategory.PROVIDER_5XX,
            ),
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

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "服务是否恢复？"},
    )
    assert response.status_code == 200
    assert response.json()["route"] == "safe_failure"

    alerts = await client.get("/api/admin/agent-observability/alerts")
    assert alerts.status_code == 200
    assert len(alerts.json()) == 1
    assert alerts.json()[0]["alert_type"] == "service"
    assert alerts.json()[0]["error_category"] == "provider_5xx"
    assert "secret-provider" not in alerts.text


async def test_run_cost_near_limit_creates_sanitized_budget_alert(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_AGENT_INVESTIGATION_MAX_COST_EUR", "0.50")
    store = await _setup_owner_agent(db_session, user_factory, store_factory, monkeypatch)

    class CostlyAgentRun:
        async def run(self, context, state, recent_messages):
            del context, recent_messages
            return AgentRunResult(
                turn=TurnResult(route="answer", content="已完成。"),
                state=state,
                attempts=[
                    ModelAttempt(
                        stage="answer",
                        provider="configured-provider",
                        model="configured-model",
                        result="success",
                        error_category=None,
                        latency_ms=120,
                        input_tokens=1_000,
                        output_tokens=300,
                        estimated_cost=0.40,
                    )
                ],
            )

    client._transport.app.state.agent_service = CostlyAgentRun()
    await _login(client, "owner")

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "请说明你的能力"},
    )
    assert response.status_code == 200

    alerts = await client.get("/api/admin/agent-observability/alerts")
    assert alerts.status_code == 200
    assert len(alerts.json()) == 1
    assert alerts.json()[0]["alert_type"] == "budget"
    assert alerts.json()[0]["error_category"] == "budget_near_limit"
    assert alerts.json()[0]["message"] == "本次模型费用接近调查预算上限，请检查预算设置。"


async def test_all_attempts_in_one_turn_share_one_run_identifier(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await _setup_owner_agent(db_session, user_factory, store_factory, monkeypatch)

    class MultiAttemptAgentRun:
        async def run(self, context, state, recent_messages):
            del context, recent_messages
            return AgentRunResult(
                turn=TurnResult(route="answer", content="已完成。"),
                state=state,
                attempts=[
                    ModelAttempt(
                        stage="plan",
                        provider="primary",
                        model="planner",
                        result="success",
                        error_category=None,
                        latency_ms=50,
                        input_tokens=100,
                        output_tokens=20,
                        estimated_cost=0.001,
                    ),
                    ModelAttempt(
                        stage="answer",
                        provider="fallback",
                        model="answerer",
                        result="success",
                        error_category=None,
                        latency_ms=80,
                        input_tokens=200,
                        output_tokens=40,
                        estimated_cost=0.002,
                        is_fallback=True,
                    ),
                ],
            )

    client._transport.app.state.agent_service = MultiAttemptAgentRun()
    await _login(client, "owner")

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "比较最近表现"},
    )
    assert response.status_code == 200

    runs = await client.get("/api/admin/agent-observability/runs")
    assert runs.status_code == 200
    assert len(runs.json()) == 2
    assert {run["run_id"] for run in runs.json()} == {runs.json()[0]["run_id"]}


async def test_insufficient_balance_alert_does_not_expose_provider_failure_text(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await _setup_owner_agent(db_session, user_factory, store_factory, monkeypatch)
    primary = FakeModelAdapter(
        plans=[
            ModelAdapterError(
                "provider-billing-detail=must-not-leak",
                category=ModelErrorCategory.INSUFFICIENT_BALANCE,
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

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "检查预算"},
    )
    assert response.status_code == 200

    alerts = await client.get("/api/admin/agent-observability/alerts")
    assert alerts.status_code == 200
    assert alerts.json()[0]["alert_type"] == "budget"
    assert alerts.json()[0]["message"] == "模型预算不可用，请检查供应商账户。"
    assert "must-not-leak" not in alerts.text
