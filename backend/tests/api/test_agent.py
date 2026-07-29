from dataclasses import dataclass, field
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.conversation import (
    AgentRunResult,
    ConversationState,
    InvestigationPartial,
    InvestigationProgress,
)
from app.agent.contracts import ModelMessage, OpenBusinessRecordsAction, TurnResult
from app.agent.release import AgentReleaseStatus
from app.agent.runtime import RuntimeContext
from app.core.config import get_settings
from app.models.identity import Store, User
from app.models.agent import AgentConversation, AgentEvidence, AgentMessage, AgentRunStat
from app.models.ledger import StoreDailyRecord
from app.models.operations import AgentSettings


@dataclass
class RecordingAgentService:
    result: TurnResult = field(
        default_factory=lambda: TurnResult(route="answer", content="这是完整回答。")
    )
    calls: list[tuple[RuntimeContext, ConversationState, list[ModelMessage]]] = field(
        default_factory=list
    )
    state: ConversationState | None = None
    progress: list[InvestigationProgress] = field(default_factory=list)
    partial: InvestigationPartial | None = None

    async def run(
        self,
        context: RuntimeContext,
        state: ConversationState,
        recent_messages: list[ModelMessage],
    ) -> AgentRunResult:
        self.calls.append((context, state, recent_messages))
        return AgentRunResult(
            turn=self.result,
            state=self.state or state,
            progress=self.progress,
            partial=self.partial,
        )


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
    assert initial.json() == {"enabled": False, "release_approved": True}
    forbidden = await client.patch("/api/admin/agent-settings", json={"enabled": True})
    assert forbidden.status_code == 403

    await _login(client, "owner")
    enabled = await client.patch("/api/admin/agent-settings", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json() == {"enabled": True, "release_approved": True}
    assert (await client.get("/api/admin/agent-settings")).json() == {
        "enabled": True,
        "release_approved": True,
    }


async def test_production_release_gate_keeps_agent_globally_disabled(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "owner")
    get_settings.cache_clear()
    await user_factory(username="owner", password="secret", role="admin")
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    await _login(client, "owner")

    from app.api.routes import agent_admin

    production = get_settings().model_copy(
        update={
            "environment": "production",
            "agent_release_report_path": None,
        }
    )
    monkeypatch.setattr(agent_admin, "get_settings", lambda: production)

    current = await client.get("/api/admin/agent-settings")
    rejected = await client.patch("/api/admin/agent-settings", json={"enabled": True})

    assert current.json() == {"enabled": False, "release_approved": False}
    assert rejected.status_code == 409
    assert rejected.json() == {"detail": "Agent 发布门禁尚未通过，保持全局关闭"}


async def test_production_release_requires_owner_enablement_for_the_approved_report(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "owner")
    get_settings.cache_clear()
    await user_factory(username="owner", password="secret", role="admin")
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    await _login(client, "owner")

    from app.api.routes import agent_admin

    approved_report_sha256 = "a" * 64
    monkeypatch.setattr(
        agent_admin,
        "agent_release_status",
        lambda _settings: AgentReleaseStatus(
            approved=True,
            blockers=[],
            approved_report_sha256=approved_report_sha256,
        ),
    )
    production = get_settings().model_copy(update={"environment": "production"})
    monkeypatch.setattr(agent_admin, "get_settings", lambda: production)

    stale = await client.get("/api/admin/agent-settings")
    enabled = await client.patch(
        "/api/admin/agent-settings",
        json={"enabled": True},
    )
    stored = await db_session.get(AgentSettings, 1)

    assert stale.json() == {"enabled": False, "release_approved": True}
    assert enabled.json() == {"enabled": True, "release_approved": True}
    assert stored is not None
    assert stored.approved_report_sha256 == approved_report_sha256


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
    owner: User = await user_factory(username="owner", password="secret", role="admin")
    store: Store = await store_factory(name="Roma", timezone="Europe/Rome")
    store.company_settlement_enabled = True
    store.wash_count_enabled = False
    store.income_items_enabled = True
    owner_id, store_id = owner.id, store.id
    await db_session.commit()
    await _login(client, "owner")
    agent_service.progress = [
        InvestigationProgress(
            status="waiting",
            message="模型服务暂时不可用，正在进行有限重试。",
        )
    ]
    agent_service.partial = InvestigationPartial(
        verified_facts=["monthly_total_revenue=400"],
        incomplete_directions=["经营日"],
        unknowns=["经营日目前无法根据已返回证据判断"],
    )
    assert (
        await client.patch("/api/admin/agent-settings", json={"enabled": True})
    ).status_code == 200

    response = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "你能做什么？"},
    )

    assert response.status_code == 200
    assert response.json()["route"] == "answer"
    assert response.json()["content"] == "这是完整回答。"
    assert response.json()["progress"] == [
        {
            "status": "waiting",
            "message": "模型服务暂时不可用，正在进行有限重试。",
        }
    ]
    assert response.json()["partial"] == {
        "verified_facts": ["monthly_total_revenue=400"],
        "incomplete_directions": ["经营日"],
        "unknowns": ["经营日目前无法根据已返回证据判断"],
    }
    assert "SQL" not in response.text
    assert "provider" not in response.text
    assert len(agent_service.calls) == 1
    context, state, recent_messages = agent_service.calls[0]
    assert state.model_dump(mode="json") == {
        "investigation_goal": "你能做什么？",
        "confirmed_period": None,
        "pending_period": None,
        "confirmed_objects": [],
        "evidence_references": [],
        "analysis_hypotheses": [],
        "pending_directions": [],
        "metrics": [],
        "filters": {},
        "comparison": None,
        "pending_clarifications": [],
    }
    assert [(message.role, message.content) for message in recent_messages] == [
        ("user", "你能做什么？")
    ]
    assert context.user_id == owner_id
    assert context.store_id == store_id
    assert context.role == "final_admin"
    assert context.store_timezone == "Europe/Rome"
    assert context.store_latitude == 45
    assert context.store_longitude == 9
    assert context.store_country_code == "IT"
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


async def test_current_conversation_restores_full_messages_and_structured_state(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    agent_service: RecordingAgentService,
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma")
    store_id = store.id
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    await _login(client, "admin")

    sent = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "保留完整问题，包括 €123 和全部细节。"},
    )
    restored = await client.get(f"/api/agent/stores/{store_id}/conversation")

    assert sent.status_code == 200
    assert restored.status_code == 200
    payload = restored.json()

    assert payload["id"] == sent.json()["conversation"]["id"]
    assert [(item["role"], item["content"]) for item in payload["messages"]] == [
        ("user", "保留完整问题，包括 €123 和全部细节。"),
        ("assistant", "这是完整回答。"),
    ]
    assert payload["state"] == {
        "investigation_goal": "保留完整问题，包括 €123 和全部细节。",
        "confirmed_period": None,
        "pending_period": None,
        "confirmed_objects": [],
        "evidence_references": [],
        "analysis_hypotheses": [],
        "pending_directions": [],
        "metrics": [],
        "filters": {},
        "comparison": None,
        "pending_clarifications": [],
    }
    assert payload["updated_at"] is not None


async def test_validated_business_records_action_is_persisted_without_scope_or_url(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    agent_service: RecordingAgentService,
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma")
    store_id = store.id
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    await _login(client, "admin")
    agent_service.result = TurnResult(
        route="answer",
        content="可查看所选月份的营业记录。",
        action=OpenBusinessRecordsAction(
            start_month="2025-01",
            end_month="2025-12",
        ),
    )

    sent = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "查看去年的全部每日记录"},
    )
    restored = await client.get(f"/api/agent/stores/{store_id}/conversation")

    assert sent.status_code == 200
    action = sent.json()["conversation"]["messages"][-1]["action"]
    assert action == {
        "type": "open_business_records",
        "start_month": "2025-01",
        "end_month": "2025-12",
    }
    assert restored.json()["messages"][-1]["action"] == action
    assert "url" not in action
    assert "store_id" not in action
    assert "user_id" not in action


async def test_current_conversations_are_isolated_by_user_and_store(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    agent_service: RecordingAgentService,
) -> None:
    await user_factory(username="first", password="secret", role="admin")
    await user_factory(username="second", password="secret", role="admin")
    first_store = await store_factory(name="Roma")
    second_store = await store_factory(name="Milano")
    first_store_id, second_store_id = first_store.id, second_store.id
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()

    await _login(client, "first")
    assert (
        await client.post(
            f"/api/agent/stores/{first_store_id}/turn",
            json={"question": "first-Roma"},
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/agent/stores/{second_store_id}/turn",
            json={"question": "first-Milano"},
        )
    ).status_code == 200

    await _login(client, "second")
    assert (
        await client.post(
            f"/api/agent/stores/{first_store_id}/turn",
            json={"question": "second-Roma"},
        )
    ).status_code == 200

    second_roma = (await client.get(f"/api/agent/stores/{first_store_id}/conversation")).json()
    await _login(client, "first")
    first_roma = (await client.get(f"/api/agent/stores/{first_store_id}/conversation")).json()
    first_milano = (await client.get(f"/api/agent/stores/{second_store_id}/conversation")).json()

    assert [item["content"] for item in second_roma["messages"]] == [
        "second-Roma",
        "这是完整回答。",
    ]
    assert [item["content"] for item in first_roma["messages"]] == [
        "first-Roma",
        "这是完整回答。",
    ]
    assert [item["content"] for item in first_milano["messages"]] == [
        "first-Milano",
        "这是完整回答。",
    ]
    assert second_roma["state"]["investigation_goal"] == "second-Roma"
    assert first_roma["state"]["investigation_goal"] == "first-Roma"
    assert first_milano["state"]["investigation_goal"] == "first-Milano"
    assert len({second_roma["id"], first_roma["id"], first_milano["id"]}) == 3


async def test_model_receives_structured_state_and_only_twelve_recent_messages(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    agent_service: RecordingAgentService,
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma")
    store_id = store.id
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    await _login(client, "admin")

    for number in range(1, 8):
        response = await client.post(
            f"/api/agent/stores/{store_id}/turn",
            json={"question": f"question-{number}"},
        )
        assert response.status_code == 200

    _, state, recent_messages = agent_service.calls[-1]
    assert state.pending_clarifications == []
    assert len(recent_messages) == 12
    assert [(message.role, message.content) for message in recent_messages] == [
        ("assistant", "这是完整回答。"),
        ("user", "question-2"),
        ("assistant", "这是完整回答。"),
        ("user", "question-3"),
        ("assistant", "这是完整回答。"),
        ("user", "question-4"),
        ("assistant", "这是完整回答。"),
        ("user", "question-5"),
        ("assistant", "这是完整回答。"),
        ("user", "question-6"),
        ("assistant", "这是完整回答。"),
        ("user", "question-7"),
    ]


async def test_reset_requires_confirmation_and_permanently_deletes_current_conversation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    agent_service: RecordingAgentService,
) -> None:
    user = await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma")
    other_store = await store_factory(name="Milano")
    store_id = store.id
    other_store_id = other_store.id
    db_session.add_all(
        [
            AgentSettings(id=1, enabled=True),
            StoreDailyRecord(
                store_id=store_id,
                date=date(2026, 7, 26),
                daily_revenue=240,
                income_mode="legacy_total",
                wash_count=4,
                is_open="营业",
                created_by=user.id,
                updated_by=user.id,
            ),
            AgentRunStat(
                user_id=user.id,
                store_id=store_id,
                role="admin",
                stage="primary",
                provider="test-provider",
                model="test-model",
                input_tokens=10,
                output_tokens=5,
                result="success",
                error_category=None,
                latency_ms=20,
                estimated_cost=0.001,
                is_fallback=False,
            ),
        ]
    )
    await db_session.commit()
    await _login(client, "admin")
    expected_state = {
        "investigation_goal": None,
        "confirmed_period": {"start": "2026-07-01", "end": "2026-07-26"},
        "pending_period": None,
        "confirmed_objects": [],
        "evidence_references": [],
        "analysis_hypotheses": [],
        "pending_directions": [],
        "metrics": ["月度总收入"],
        "filters": {"记录天气": ["晴"]},
        "comparison": {
            "period": {"start": "2026-06-01", "end": "2026-06-30"},
            "label": "完整上月",
        },
        "pending_clarifications": ["请确认收入分类"],
    }
    agent_service.state = ConversationState.model_validate(expected_state)
    sent = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "这条消息之后会永久删除"},
    )
    assert sent.status_code == 200
    other_sent = await client.post(
        f"/api/agent/stores/{other_store_id}/turn",
        json={"question": "另一个门店仍在进行的调查"},
    )
    assert other_sent.status_code == 200
    conversation_id = sent.json()["conversation"]["id"]
    persisted = await db_session.get(AgentConversation, conversation_id)
    assert persisted is not None
    db_session.add(
        AgentEvidence(
            conversation_id=conversation_id,
            payload={"raw_business_payload": "must be permanently deleted"},
        )
    )
    await db_session.commit()
    saved_state = (await client.get(f"/api/agent/stores/{store_id}/conversation")).json()["state"]
    assert saved_state == expected_state

    missing_confirmation = await client.request(
        "DELETE",
        f"/api/agent/stores/{store_id}/conversation",
        json={"confirmation": "no"},
    )
    assert missing_confirmation.status_code == 422
    assert (
        len((await client.get(f"/api/agent/stores/{store_id}/conversation")).json()["messages"])
        == 2
    )

    deleted = await client.request(
        "DELETE",
        f"/api/agent/stores/{store_id}/conversation",
        json={"confirmation": "permanently_delete"},
    )
    await client.post("/api/auth/logout")
    await _login(client, "admin")
    restored = await client.get(f"/api/agent/stores/{store_id}/conversation")
    other_restored = await client.get(f"/api/agent/stores/{other_store_id}/conversation")

    assert deleted.status_code == 204
    assert restored.status_code == 200
    assert restored.json() == {
        "id": None,
        "messages": [],
        "state": {
            "investigation_goal": None,
            "confirmed_period": None,
            "pending_period": None,
            "confirmed_objects": [],
            "evidence_references": [],
            "analysis_hypotheses": [],
            "pending_directions": [],
            "metrics": [],
            "filters": {},
            "comparison": None,
            "pending_clarifications": [],
        },
        "created_at": None,
        "updated_at": None,
    }
    assert [message["content"] for message in other_restored.json()["messages"]] == [
        "另一个门店仍在进行的调查",
        "这是完整回答。",
    ]
    assert await db_session.scalar(select(func.count()).select_from(AgentConversation)) == 1
    assert await db_session.scalar(select(func.count()).select_from(AgentMessage)) == 2
    assert await db_session.scalar(select(func.count()).select_from(AgentEvidence)) == 0
    assert await db_session.scalar(select(func.count()).select_from(StoreDailyRecord)) == 1
    assert await db_session.scalar(select(func.count()).select_from(AgentRunStat)) == 1


async def test_in_flight_turn_cannot_recreate_a_conversation_after_reset(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma")
    store_id = store.id
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()

    class ResetDuringRun:
        async def run(
            self,
            context: RuntimeContext,
            state: ConversationState,
            recent_messages: list[ModelMessage],
        ) -> AgentRunResult:
            del context, recent_messages
            await db_session.execute(delete(AgentConversation))
            await db_session.commit()
            return AgentRunResult(
                turn=TurnResult(route="answer", content="不应重新出现"),
                state=state,
            )

    client._transport.app.state.agent_service = ResetDuringRun()
    await _login(client, "admin")

    response = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "请求进行时重置"},
    )

    assert response.status_code == 409
    assert (await client.get(f"/api/agent/stores/{store_id}/conversation")).json()["messages"] == []


async def test_in_flight_turn_revalidates_authorization_before_returning_answer(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma")
    admin_id, store_id = admin.id, store.id
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()

    class RevokeDuringRun:
        async def run(
            self,
            context: RuntimeContext,
            state: ConversationState,
            recent_messages: list[ModelMessage],
        ) -> AgentRunResult:
            del context, recent_messages
            current_admin = await db_session.get(User, admin_id)
            assert current_admin is not None
            current_admin.role = "user"
            await db_session.commit()
            return AgentRunResult(
                turn=TurnResult(route="answer", content="撤权后不应返回"),
                state=state,
            )

    client._transport.app.state.agent_service = RevokeDuringRun()
    await _login(client, "admin")

    response = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "请求进行时撤销权限"},
    )

    assert response.status_code == 403
    messages = list(await db_session.scalars(select(AgentMessage).order_by(AgentMessage.id)))
    assert [(message.role, message.content) for message in messages] == [
        ("user", "请求进行时撤销权限")
    ]
