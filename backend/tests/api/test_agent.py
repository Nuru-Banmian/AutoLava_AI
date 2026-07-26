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
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
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
    assert model.plan_calls == 1
    assert model.answer_calls == 1


@pytest.mark.parametrize(
    ("metric", "question", "unit", "version", "expected_result"),
    (
        (
            "daily_ledger_revenue",
            "本月每日台账营业额是多少？",
            "EUR",
            "daily_ledger_revenue.v1",
            {"daily_ledger_revenue": 200},
        ),
        (
            "confirmed_settlement_income",
            "本月已确认公司结算收入是多少？",
            "EUR",
            "confirmed_settlement_income.v1",
            {"confirmed_settlement_income": 100},
        ),
        (
            "operating_days",
            "本月有多少经营日？",
            "day",
            "operating_days.v1",
            {"operating_days": 2},
        ),
        (
            "operating_day_average_ledger_revenue",
            "本月经营日均台账营业额是多少？",
            "EUR/operating_day",
            "operating_day_average_ledger_revenue.v1",
            {
                "daily_ledger_revenue": 200,
                "operating_days": 2,
                "operating_day_average_ledger_revenue": 100,
            },
        ),
        (
            "monthly_daily_average_income",
            "本月月度日均收入是多少？",
            "EUR/operating_day",
            "monthly_daily_average_income.v1",
            {
                "daily_ledger_revenue": 200,
                "confirmed_settlement_income": 100,
                "monthly_total_revenue": 300,
                "operating_days": 2,
                "monthly_daily_average_income": 150,
            },
        ),
        (
            "income_category_amount",
            "本月各收入分类金额是多少？",
            "EUR",
            "income_category_amount.v1",
            {
                "amount": 200,
                "categories": [
                    {
                        "category_id": "included",
                        "category_name": "历史现金",
                        "include_in_total": True,
                        "sort_order": 3,
                        "amount": 200,
                    }
                ],
            },
        ),
        (
            "other_data_amount",
            "本月其他数据金额是多少？",
            "EUR",
            "other_data_amount.v1",
            {
                "amount": 30,
                "categories": [
                    {
                        "category_id": "other",
                        "category_name": "历史其他",
                        "include_in_total": False,
                        "sort_order": 4,
                        "amount": 30,
                    }
                ],
            },
        ),
    ),
)
async def test_core_business_metric_http_gold_paths_use_historical_snapshots_and_store_scope(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    metric: str,
    question: str,
    unit: str,
    version: str,
    expected_result: dict[str, object],
) -> None:
    user = await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    other_store = await store_factory(name="Milano", timezone="Europe/Rome")
    included = IncomeCategory(
        store_id=store.id,
        name="当前现金",
        include_in_total=False,
        is_active=True,
        sort_order=99,
    )
    other = IncomeCategory(
        store_id=store.id,
        name="当前其他",
        include_in_total=True,
        is_active=True,
        sort_order=98,
    )
    db_session.add_all([included, other])
    await db_session.flush()
    store_id = store.id
    included_id = included.id
    other_id = other.id
    records = [
        StoreDailyRecord(
            store_id=store.id,
            date=date(2026, 7, 1),
            daily_revenue=120,
            income_mode="composed",
            wash_count=None,
            is_open="营业",
            created_by=user.id,
            updated_by=user.id,
        ),
        StoreDailyRecord(
            store_id=store.id,
            date=date(2026, 7, 2),
            daily_revenue=80,
            income_mode="composed",
            wash_count=None,
            is_open="提前休息",
            created_by=user.id,
            updated_by=user.id,
        ),
        StoreDailyRecord(
            store_id=store.id,
            date=date(2026, 7, 3),
            daily_revenue=0,
            income_mode="legacy_total",
            wash_count=None,
            is_open="休息",
            created_by=user.id,
            updated_by=user.id,
        ),
        StoreDailyRecord(
            store_id=other_store.id,
            date=date(2026, 7, 1),
            daily_revenue=9_000,
            income_mode="legacy_total",
            wash_count=None,
            is_open="营业",
            created_by=user.id,
            updated_by=user.id,
        ),
    ]
    db_session.add_all(records)
    await db_session.flush()
    db_session.add_all(
        [
            DailyIncomeItem(
                record_id=records[0].id,
                category_id=included.id,
                category_name="历史现金",
                include_in_total=True,
                sort_order=3,
                amount=120,
            ),
            DailyIncomeItem(
                record_id=records[0].id,
                category_id=other.id,
                category_name="历史其他",
                include_in_total=False,
                sort_order=4,
                amount=10,
            ),
            DailyIncomeItem(
                record_id=records[1].id,
                category_id=included.id,
                category_name="历史现金",
                include_in_total=True,
                sort_order=3,
                amount=80,
            ),
            DailyIncomeItem(
                record_id=records[1].id,
                category_id=other.id,
                category_name="历史其他",
                include_in_total=False,
                sort_order=4,
                amount=20,
            ),
        ]
    )
    company = SettlementCompany(
        store_id=store.id,
        name="Acme",
        normalized_name="acme",
        is_active=True,
        archived_at=None,
        created_by=user.id,
        updated_by=user.id,
    )
    other_company = SettlementCompany(
        store_id=other_store.id,
        name="Other",
        normalized_name="other",
        is_active=True,
        archived_at=None,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add_all([company, other_company])
    await db_session.flush()
    db_session.add_all(
        [
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=100,
                status="confirmed",
                created_by=user.id,
                updated_by=user.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=999,
                status="pending",
                created_by=user.id,
                updated_by=user.id,
            ),
            SettlementRecord(
                store_id=other_store.id,
                company_id=other_company.id,
                company_name=other_company.name,
                opening_month=date(2026, 7, 1),
                amount=8_000,
                status="confirmed",
                created_by=user.id,
                updated_by=user.id,
            ),
        ]
    )
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()

    @asynccontextmanager
    async def session_factory():
        yield db_session

    request: dict[str, object] = {
        "kind": "business_metrics",
        "metric": metric,
    }
    if metric in {"income_category_amount", "other_data_amount"}:
        request["group_by"] = "income_category"
    model = FakeModelAdapter(
        plans=[
            {
                "route": "evidence",
                "evidence_plan": {"requests": [request]},
            }
        ],
        answers=["模型不能改写后端计算。"],
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
        json={"question": question},
    )

    assert response.status_code == 200
    assert response.json()["route"] == "answer"
    assert response.json()["conversation"]["state"]["confirmed_period"] == {
        "start": "2026-07-01",
        "end": "2026-07-26",
    }
    evidence = await db_session.scalar(select(AgentEvidence).order_by(AgentEvidence.id.desc()))
    assert evidence is not None
    resolved_expected = expected_result
    if metric in {"income_category_amount", "other_data_amount"}:
        resolved_expected = {
            **expected_result,
            "categories": [
                {
                    **expected_result["categories"][0],
                    "category_id": (
                        included_id if metric == "income_category_amount" else other_id
                    ),
                }
            ],
        }
    assert evidence.payload["result"] == resolved_expected
    assert evidence.payload["unit"] == unit
    assert evidence.payload["calculation_version"] == version
    assert evidence.payload["current_store"] == {"id": store_id}


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
