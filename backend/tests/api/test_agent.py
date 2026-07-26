from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.conversation import AgentRunResult, ConversationState
from app.agent.contracts import ModelMessage, TurnResult
from app.agent.model import FakeModelAdapter
from app.agent.runtime import RuntimeContext
from app.agent.service import AgentService
from app.agent.workflow import AgentTurnWorkflow
from app.core.config import get_settings
from app.models.identity import Store, User
from app.models.agent import AgentConversation, AgentEvidence, AgentMessage
from app.models.ledger import StoreDailyRecord
from app.models.operations import AgentSettings
from app.models.settlement import SettlementCompany, SettlementRecord


class NeverEvidenceCollector:
    async def collect(self, plan, context):
        del plan, context
        raise AssertionError("This test must not collect business evidence")


@dataclass
class RecordingAgentService:
    result: TurnResult = field(
        default_factory=lambda: TurnResult(route="answer", content="这是完整回答。")
    )
    calls: list[tuple[RuntimeContext, ConversationState, list[ModelMessage]]] = field(
        default_factory=list
    )
    state: ConversationState | None = None

    async def run(
        self,
        context: RuntimeContext,
        state: ConversationState,
        recent_messages: list[ModelMessage],
    ) -> AgentRunResult:
        self.calls.append((context, state, recent_messages))
        return AgentRunResult(turn=self.result, state=self.state or state)


async def _login(client: AsyncClient, username: str, password: str = "secret") -> None:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200


def _install_business_evidence_service(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    plans: list[dict[str, object]],
    now: datetime = datetime(2026, 7, 26, 12, 0),
) -> FakeModelAdapter:
    @asynccontextmanager
    async def session_factory():
        yield db_session

    model = FakeModelAdapter(
        plans=plans,
        answers=["模型不能改写后端证据。"] * len(plans),
    )
    client._transport.app.state.agent_service = AgentService(
        AgentTurnWorkflow(
            model=model,
            evidence_collector=BusinessEvidenceCollector(
                session_factory,
                now=lambda _timezone: now,
            ),
        )
    )
    return model


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
    assert response.json()["route"] == "answer"
    assert response.json()["content"] == "这是完整回答。"
    assert len(agent_service.calls) == 1
    context, state, recent_messages = agent_service.calls[0]
    assert state.model_dump(mode="json") == {
        "confirmed_period": None,
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


async def test_agent_http_turn_returns_direct_answers_and_ends_on_clarification(
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
    model = FakeModelAdapter(
        plans=[
            {"route": "direct_answer", "answer": "我可以回答一般问题。"},
            {"route": "clarify", "question": "你想了解哪个时间范围？"},
        ]
    )
    client._transport.app.state.agent_service = AgentService(
        AgentTurnWorkflow(
            model=model,
            evidence_collector=NeverEvidenceCollector(),
        )
    )
    await _login(client, "admin")

    direct = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "你能做什么？"},
    )
    clarification = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "帮我看看"},
    )

    assert direct.status_code == 200
    assert {key: direct.json()[key] for key in ("route", "content")} == {
        "route": "answer",
        "content": "我可以回答一般问题。",
    }
    assert clarification.status_code == 200
    assert {
        key: clarification.json()[key] for key in ("route", "content")
    } == {
        "route": "clarify",
        "content": "你想了解哪个时间范围？",
    }
    assert clarification.json()["conversation"]["state"][
        "pending_clarifications"
    ] == ["你想了解哪个时间范围？"]
    assert model.plan_calls == 2
    assert model.answer_calls == 0


async def test_monthly_total_revenue_http_gold_path_persists_raw_evidence_safely(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    store_id = store.id
    db_session.add(AgentSettings(id=1, enabled=True))
    db_session.add(
        StoreDailyRecord(
            store_id=store_id,
            date=date(2026, 7, 5),
            daily_revenue=240,
            income_mode="legacy_total",
            wash_count=4,
            is_open="营业",
            weather="晴",
            weather_auto=None,
            weather_code=None,
            temperature_max=None,
            temperature_min=None,
            precipitation=None,
            activity=None,
            weather_edited=False,
            scanned=False,
            created_by=user.id,
            updated_by=user.id,
        )
    )
    company = SettlementCompany(
        store_id=store_id,
        name="Acme",
        normalized_name="acme",
        is_active=True,
        archived_at=None,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(company)
    await db_session.flush()
    db_session.add_all(
        [
            SettlementRecord(
                store_id=store_id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=160,
                status="confirmed",
                created_by=user.id,
                updated_by=user.id,
            ),
            SettlementRecord(
                store_id=store_id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=999,
                status="pending",
                created_by=user.id,
                updated_by=user.id,
            ),
        ]
    )
    await db_session.commit()

    @asynccontextmanager
    async def session_factory():
        yield db_session

    expected_answer = (
        "2026-07-01 至 2026-07-26 的月度总收入为 400 欧元，"
        "其中每日台账营业额 240 欧元，已确认公司结算收入 160 欧元。"
        "所选期间有 25 个日期没有每日台账；这不表示门店本应营业。"
    )
    model = FakeModelAdapter(
        plans=[
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {
                            "kind": "business_metrics",
                            "metric": "monthly_total_revenue",
                        }
                    ]
                },
            }
        ],
        answers=[expected_answer],
    )
    client._transport.app.state.agent_service = AgentService(
        AgentTurnWorkflow(
            model=model,
            evidence_collector=BusinessEvidenceCollector(
                session_factory,
                now=lambda _timezone: datetime(2026, 7, 26, 12, 0),
            ),
        )
    )
    await _login(client, "admin")

    response = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "本月收入是多少？"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"] == "answer"
    assert payload["content"] == expected_answer
    assert "evidence" not in payload
    assert payload["conversation"]["state"]["confirmed_period"] == {
        "start": "2026-07-01",
        "end": "2026-07-26",
    }
    assert payload["conversation"]["state"]["metrics"] == ["月度总收入"]
    evidence = await db_session.scalar(select(AgentEvidence))
    assert evidence is not None
    assert evidence.payload["result"] == {
        "daily_ledger_revenue": 240,
        "confirmed_settlement_income": 160,
        "monthly_total_revenue": 400,
    }
    assert evidence.payload["period"] == {
        "start": "2026-07-01",
        "end": "2026-07-26",
    }
    assert "companies" not in evidence.payload
    assert "records" not in evidence.payload
    assert "Acme" not in evidence.payload["summary"]
    assert 999 not in evidence.payload["result"].values()
    assert model.plan_calls == 1
    assert model.answer_calls == 1


async def test_settlement_detail_agent_queries_are_gated_scoped_and_identity_consistent(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "owner")
    get_settings.cache_clear()
    admin = await user_factory(username="admin", password="secret", role="admin")
    owner = await user_factory(username="owner", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    other_store = await store_factory(name="Milano", timezone="Europe/Rome")
    store.company_settlement_enabled = True
    other_store.company_settlement_enabled = True
    db_session.add(AgentSettings(id=1, enabled=True))

    acme = SettlementCompany(
        store_id=store.id,
        name="Acme",
        normalized_name="acme",
        is_active=True,
        archived_at=None,
        created_by=admin.id,
        updated_by=admin.id,
    )
    beta = SettlementCompany(
        store_id=store.id,
        name="Beta",
        normalized_name="beta",
        is_active=False,
        archived_at=datetime(2026, 7, 20),
        created_by=admin.id,
        updated_by=admin.id,
    )
    secret = SettlementCompany(
        store_id=other_store.id,
        name="Secret",
        normalized_name="secret",
        is_active=True,
        archived_at=None,
        created_by=owner.id,
        updated_by=owner.id,
    )
    db_session.add_all([acme, beta, secret])
    await db_session.flush()
    confirmed = SettlementRecord(
        store_id=store.id,
        company_id=acme.id,
        company_name=acme.name,
        opening_month=date(2026, 7, 1),
        amount=200,
        status="confirmed",
        created_by=admin.id,
        updated_by=admin.id,
    )
    db_session.add_all(
        [
            SettlementRecord(
                store_id=store.id,
                company_id=acme.id,
                company_name=acme.name,
                opening_month=date(2026, 7, 1),
                amount=100,
                status="pending",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            confirmed,
            SettlementRecord(
                store_id=store.id,
                company_id=beta.id,
                company_name=beta.name,
                opening_month=date(2026, 7, 1),
                amount=300,
                status="pending",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            SettlementRecord(
                store_id=other_store.id,
                company_id=secret.id,
                company_name=secret.name,
                opening_month=date(2026, 7, 1),
                amount=9999,
                status="confirmed",
                created_by=owner.id,
                updated_by=owner.id,
            ),
        ]
    )
    await db_session.commit()
    store_id = store.id
    confirmed_id = confirmed.id

    _install_business_evidence_service(
        client,
        db_session,
        plans=[
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {"kind": "settlement_details", "status": "pending"}
                    ]
                },
            },
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {"kind": "settlement_details", "company_name": "Acme"}
                    ]
                },
            },
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {"kind": "settlement_details", "company_name": "Acme"}
                    ]
                },
            },
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {"kind": "settlement_details", "company_name": "Acme"}
                    ]
                },
            },
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {"kind": "settlement_details", "company_name": "Secret"}
                    ]
                },
            },
        ],
    )
    await _login(client, "admin")

    pending = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "本月有哪些待到账开票记录？"},
    )
    before_revoke = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "Acme 公司金额是多少？"},
    )
    revoked = await client.post(
        f"/api/settlements/{store_id}/records/{confirmed_id}/revoke-confirmation",
        json={"revision": 1},
    )
    after_revoke = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "撤销到账确认后，Acme 公司金额是多少？"},
    )

    assert pending.status_code == 200
    assert "待到账 400 欧元（2 笔）" in pending.json()["content"]
    assert "已确认 0 欧元（0 笔）" in pending.json()["content"]
    assert "Acme" in pending.json()["content"]
    assert "Beta" in pending.json()["content"]
    assert "Secret" not in pending.json()["content"]
    assert "9999" not in pending.json()["content"]
    assert before_revoke.status_code == 200
    assert "待到账 100 欧元（1 笔）" in before_revoke.json()["content"]
    assert "已确认 200 欧元（1 笔）" in before_revoke.json()["content"]
    assert "Beta" not in before_revoke.json()["content"]
    assert revoked.status_code == 200
    assert after_revoke.status_code == 200
    assert "待到账 300 欧元（2 笔）" in after_revoke.json()["content"]
    assert "已确认 0 欧元（0 笔）" in after_revoke.json()["content"]

    await _login(client, "owner")
    owner_result = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "Acme 公司金额是多少？"},
    )
    cross_store = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "Secret 公司金额是多少？"},
    )

    assert owner_result.status_code == 200
    assert owner_result.json()["content"] == after_revoke.json()["content"]
    assert cross_store.status_code == 200
    assert "没有名为「Secret」的结算公司" in cross_store.json()["content"]
    assert "9999" not in cross_store.json()["content"]

    evidence_rows = list(
        (await db_session.scalars(select(AgentEvidence).order_by(AgentEvidence.id))).all()
    )
    settlement_payload = evidence_rows[0].payload
    assert settlement_payload["current_store"] == {"id": store_id}
    assert all("id" not in record for record in settlement_payload["result"]["records"])
    assert all("id" not in company for company in settlement_payload["result"]["companies"])
    serialized = str(settlement_payload).casefold()
    for sensitive_field in (
        "contact",
        "email",
        "phone",
        "payment",
        "account",
        "iban",
        "tax",
        "invoice_details",
    ):
        assert sensitive_field not in serialized


async def test_disabled_settlement_details_are_refused_while_confirmed_history_stays_in_revenue(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    store.company_settlement_enabled = False
    db_session.add(AgentSettings(id=1, enabled=True))
    company = SettlementCompany(
        store_id=store.id,
        name="Historical",
        normalized_name="historical",
        is_active=True,
        archived_at=None,
        created_by=admin.id,
        updated_by=admin.id,
    )
    db_session.add(company)
    await db_session.flush()
    db_session.add(
        SettlementRecord(
            store_id=store.id,
            company_id=company.id,
            company_name=company.name,
            opening_month=date(2026, 7, 1),
            amount=450,
            status="confirmed",
            created_by=admin.id,
            updated_by=admin.id,
        )
    )
    await db_session.commit()
    store_id = store.id
    _install_business_evidence_service(
        client,
        db_session,
        plans=[
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [{"kind": "settlement_details"}],
                },
            },
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {
                            "kind": "business_metrics",
                            "metric": "monthly_total_revenue",
                        }
                    ],
                },
            },
        ],
    )
    await _login(client, "admin")

    details = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "本月开票记录有哪些？"},
    )
    revenue = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "本月收入是多少？"},
    )

    assert details.status_code == 200
    assert details.json()["route"] == "answer"
    assert details.json()["content"] == (
        "当前门店未启用公司结算，不能查询结算公司或开票记录明细。"
    )
    assert revenue.status_code == 200
    assert "月度总收入为 450 欧元" in revenue.json()["content"]
    evidence_rows = list(
        (await db_session.scalars(select(AgentEvidence).order_by(AgentEvidence.id))).all()
    )
    assert evidence_rows[0].payload["status"] == "refused"
    assert evidence_rows[1].payload["result"]["confirmed_settlement_income"] == 450


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
        "confirmed_period": None,
        "metrics": [],
        "filters": {},
        "comparison": None,
        "pending_clarifications": [],
    }
    assert payload["updated_at"] is not None


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

    second_roma = (
        await client.get(f"/api/agent/stores/{first_store_id}/conversation")
    ).json()
    await _login(client, "first")
    first_roma = (
        await client.get(f"/api/agent/stores/{first_store_id}/conversation")
    ).json()
    first_milano = (
        await client.get(f"/api/agent/stores/{second_store_id}/conversation")
    ).json()

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
    await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma")
    store_id = store.id
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    await _login(client, "admin")
    expected_state = {
        "confirmed_period": {"start": "2026-07-01", "end": "2026-07-26"},
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
    conversation_id = sent.json()["conversation"]["id"]
    persisted = await db_session.get(AgentConversation, conversation_id)
    assert persisted is not None
    db_session.add(
        AgentEvidence(
            conversation_id=conversation_id,
            payload={"summary": "raw backend-validated evidence"},
        )
    )
    await db_session.commit()
    saved_state = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()["state"]
    assert saved_state == expected_state

    missing_confirmation = await client.request(
        "DELETE",
        f"/api/agent/stores/{store_id}/conversation",
        json={"confirmation": "no"},
    )
    assert missing_confirmation.status_code == 422
    assert len(
        (
            await client.get(f"/api/agent/stores/{store_id}/conversation")
        ).json()["messages"]
    ) == 2

    deleted = await client.request(
        "DELETE",
        f"/api/agent/stores/{store_id}/conversation",
        json={"confirmation": "permanently_delete"},
    )
    restored = await client.get(f"/api/agent/stores/{store_id}/conversation")

    assert deleted.status_code == 204
    assert restored.status_code == 200
    assert restored.json() == {
        "id": None,
        "messages": [],
        "state": {
            "confirmed_period": None,
            "metrics": [],
            "filters": {},
            "comparison": None,
            "pending_clarifications": [],
        },
        "created_at": None,
        "updated_at": None,
    }
    assert (
        await db_session.scalar(select(func.count()).select_from(AgentConversation))
        == 0
    )
    assert await db_session.scalar(select(func.count()).select_from(AgentMessage)) == 0
    assert await db_session.scalar(select(func.count()).select_from(AgentEvidence)) == 0


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
    assert (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()["messages"] == []
