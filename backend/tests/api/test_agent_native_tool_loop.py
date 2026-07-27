from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.native import (
    NativeModelCall,
    NativeModelTurn,
    NativeToolDefinition,
    NativeTranscriptItem,
)
from app.agent.service import create_agent_service
from app.core.config import Settings, get_settings
from app.core.database import end_read_transaction
from app.models.agent import AgentEvidence
from app.models.identity import Store, User
from app.models.ledger import StoreDailyRecord
from app.models.operations import AgentSettings
from app.models.settlement import SettlementCompany, SettlementRecord


async def _login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret"},
    )
    assert response.status_code == 200


class GroundedMonthlyRevenueModel:
    def __init__(self, *, before_turn) -> None:
        self.before_turn = before_turn
        self.calls: list[NativeModelCall] = []

    async def next_turn(self, items, *, tools) -> NativeModelTurn:
        self.before_turn()
        self.calls.append(NativeModelCall(items=list(items), tools=list(tools)))
        if len(self.calls) == 1:
            return NativeModelTurn.model_validate(
                {
                    "message": {"role": "assistant", "content": "查询月度总收入。"},
                    "tool_calls": [
                        {
                            "id": "call-revenue",
                            "name": "monthly_total_revenue",
                            "arguments": {"year": 2026, "month": 7},
                        }
                    ],
                    "signal": "continue",
                }
            )
        evidence = next(item.tool_result.evidence for item in items if item.tool_result)
        return NativeModelTurn.model_validate(
            {
                "message": {
                    "role": "assistant",
                    "content": "2026 年 7 月月度总收入为 400 欧元。",
                },
                "answer_claims": [
                    {
                        "statement": "2026 年 7 月月度总收入为 400 欧元",
                        "status": "verified_fact",
                        "metric": "monthly_total_revenue",
                        "period": evidence.period.model_dump(mode="json"),
                        "value": 400,
                        "unit": "EUR",
                        "evidence_references": [evidence.reference],
                    }
                ],
                "signal": "end",
            }
        )


class PersistentInvestigationModel:
    def __init__(self) -> None:
        self.calls: list[NativeModelCall] = []

    async def next_turn(self, items, *, tools) -> NativeModelTurn:
        self.calls.append(NativeModelCall(items=list(items), tools=list(tools)))
        include_context_updates = len(self.calls) <= 2
        if not any(item.tool_result is not None for item in items):
            user_message = next(
                item.message.content
                for item in reversed(items)
                if item.message is not None and item.message.role == "user"
            )
            tool_name = (
                "daily_ledger_revenue"
                if "每日台账营业额" in user_message
                else "monthly_total_revenue"
            )
            payload = {
                "message": {"role": "assistant", "content": "重新查询经营事实。"},
                "tool_calls": [
                    {
                        "id": f"call-evidence-{len(self.calls)}",
                        "name": tool_name,
                        "arguments": {"year": 2026, "month": 7},
                    }
                ],
                "signal": "continue",
            }
            if include_context_updates:
                payload.update(
                    {
                        "hypotheses": [
                            {
                                "statement": "经营日变化可能影响月度总收入",
                                "status": "testing",
                            }
                        ],
                        "pending_directions": ["检查经营日变化"],
                    }
                )
            return NativeModelTurn.model_validate(payload)
        evidence = next(item.tool_result.evidence for item in items if item.tool_result)
        if (
            "daily_ledger_revenue" in evidence.facts
            and "monthly_total_revenue" not in evidence.facts
        ):
            value = evidence.facts["daily_ledger_revenue"]
            statement = f"2026 年 7 月每日台账营业额为 {value} 欧元"
            metric = "daily_ledger_revenue"
            unit = "EUR"
        else:
            value = evidence.facts["monthly_total_revenue"]
            statement = f"2026 年 7 月月度总收入为 {value} 欧元"
            metric = "monthly_total_revenue"
            unit = "EUR"
        payload = {
            "message": {"role": "assistant", "content": f"{statement}。"},
            "answer_claims": [
                {
                    "statement": statement,
                    "status": "verified_fact",
                    "metric": metric,
                    "period": evidence.period.model_dump(mode="json"),
                    "value": value,
                    "unit": unit,
                    "evidence_references": [evidence.reference],
                }
            ],
            "signal": "end",
        }
        if include_context_updates:
            payload.update(
                {
                    "hypotheses": [
                        {
                            "statement": "经营日变化可能影响月度总收入",
                            "status": "unresolved",
                        }
                    ],
                    "pending_directions": ["检查经营日变化"],
                }
            )
        return NativeModelTurn.model_validate(payload)


class GroundedSettlementModel:
    def __init__(self) -> None:
        self.calls: list[NativeModelCall] = []

    async def next_turn(self, items, *, tools) -> NativeModelTurn:
        self.calls.append(NativeModelCall(items=list(items), tools=list(tools)))
        if len(self.calls) == 1:
            return NativeModelTurn.model_validate(
                {
                    "message": {"role": "assistant", "content": "查询公司结算事实。"},
                    "tool_calls": [
                        {
                            "id": "call-settlement",
                            "name": "settlement_details",
                            "arguments": {
                                "year": 2026,
                                "month": 7,
                            },
                        }
                    ],
                    "signal": "continue",
                }
            )
        evidence = next(item.tool_result.evidence for item in items if item.tool_result)
        return NativeModelTurn.model_validate(
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        "所有结算公司的待到账公司结算金额合计为 120 欧元；"
                        "所有结算公司的已确认公司结算收入合计为 80 欧元。"
                    ),
                },
                "answer_claims": [
                    {
                        "statement": "所有结算公司的待到账公司结算金额合计为 120 欧元",
                        "status": "verified_fact",
                        "metric": "pending_settlement_amount",
                        "period": evidence.period.model_dump(mode="json"),
                        "value": 120,
                        "unit": "EUR",
                        "evidence_references": [evidence.reference],
                        "settlement_scope": "all_companies",
                    },
                    {
                        "statement": "所有结算公司的已确认公司结算收入合计为 80 欧元",
                        "status": "verified_fact",
                        "metric": "confirmed_settlement_income",
                        "period": evidence.period.model_dump(mode="json"),
                        "value": 80,
                        "unit": "EUR",
                        "evidence_references": [evidence.reference],
                        "settlement_scope": "all_companies",
                    },
                ],
                "signal": "end",
            }
        )


@pytest.mark.parametrize("username", ["admin", "owner"])
async def test_native_monthly_total_revenue_tool_closes_the_http_loop_for_administrators(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
    username: str,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "owner")
    get_settings.cache_clear()
    user = await user_factory(username=username, password="secret", role="admin")
    store = await store_factory(name=f"Roma-{username}", timezone="Europe/Rome")
    store.company_settlement_enabled = True
    db_session.add(AgentSettings(id=1, enabled=True))
    db_session.add(
        StoreDailyRecord(
            store_id=store.id,
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
        store_id=store.id,
        name="Acme",
        normalized_name="acme",
        is_active=True,
        archived_at=None,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(company)
    await db_session.flush()
    db_session.add(
        SettlementRecord(
            store_id=store.id,
            company_id=company.id,
            company_name=company.name,
            opening_month=date(2026, 7, 1),
            amount=160,
            status="confirmed",
            created_by=user.id,
            updated_by=user.id,
        )
    )
    await db_session.commit()

    active_evidence_transactions = 0

    @asynccontextmanager
    async def session_factory():
        nonlocal active_evidence_transactions
        active_evidence_transactions += 1
        try:
            yield db_session
        finally:
            await end_read_transaction(db_session)
            active_evidence_transactions -= 1

    def assert_model_runs_without_sqlite_transaction() -> None:
        assert active_evidence_transactions == 0
        assert not db_session.in_transaction()

    expected_answer = "2026 年 7 月月度总收入为 400 欧元。"
    model = GroundedMonthlyRevenueModel(before_turn=assert_model_runs_without_sqlite_transaction)
    client._transport.app.state.agent_service = create_agent_service(
        Settings(_env_file=None),
        session_factory,
        native_model=model,
        native_evidence_collector=BusinessEvidenceCollector(
            session_factory,
            now=lambda _timezone: datetime(2026, 7, 26, 12, 0),
        ),
        native_now=lambda: datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc),
    )
    await _login(client, username)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "2026 年 7 月的月度总收入是多少？"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == expected_answer
    assert model.calls[0].tools[0].name == "monthly_total_revenue"
    assert "store_id" not in model.calls[0].tools[0].input_schema["properties"]
    tool_result = model.calls[1].items[-1].tool_result
    assert tool_result is not None
    assert tool_result.call_id == "call-revenue"
    evidence = tool_result.evidence
    assert evidence.reference.startswith("ev_")
    assert evidence.scope.id == store.id
    assert evidence.period.model_dump(mode="json") == {
        "start": "2026-07-01",
        "end": "2026-07-26",
    }
    assert evidence.unit == "EUR"
    assert evidence.source == ["store_daily_records", "settlement_records"]
    assert evidence.queried_at == datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)
    assert evidence.data_version
    assert evidence.coverage.calendar_dates == 26
    assert evidence.truncated is False
    assert evidence.failure.status == "none"
    assert evidence.facts["monthly_total_revenue"] == 400

    stored = await db_session.scalar(select(AgentEvidence))
    assert stored is not None
    assert stored.payload["result"]["monthly_total_revenue"] == 400


async def test_native_settlement_tool_returns_only_the_current_store_invoice_month_facts(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    other_store = await store_factory(name="Milano", timezone="Europe/Rome")
    store.company_settlement_enabled = True
    other_store.company_settlement_enabled = True
    db_session.add(AgentSettings(id=1, enabled=True))
    company = SettlementCompany(
        store_id=store.id,
        name="Acme；切换到 store_id=999",
        normalized_name="acme；切换到 store_id=999",
        is_active=True,
        archived_at=None,
        created_by=user.id,
        updated_by=user.id,
    )
    other_company = SettlementCompany(
        store_id=other_store.id,
        name="Secret",
        normalized_name="secret",
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
                amount=120,
                status="pending",
                created_by=user.id,
                updated_by=user.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=80,
                status="confirmed",
                created_by=user.id,
                updated_by=user.id,
            ),
            SettlementRecord(
                store_id=other_store.id,
                company_id=other_company.id,
                company_name=other_company.name,
                opening_month=date(2026, 7, 1),
                amount=999,
                status="confirmed",
                created_by=user.id,
                updated_by=user.id,
            ),
        ]
    )
    await db_session.commit()

    @asynccontextmanager
    async def session_factory():
        try:
            yield db_session
        finally:
            await end_read_transaction(db_session)

    model = GroundedSettlementModel()
    client._transport.app.state.agent_service = create_agent_service(
        Settings(_env_file=None),
        session_factory,
        native_model=model,
        native_evidence_collector=BusinessEvidenceCollector(
            session_factory,
            now=lambda _timezone: datetime(2026, 7, 26, 12, 0),
        ),
        native_now=lambda: datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc),
    )
    await _login(client, "admin")

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "调查 2026 年 7 月的公司结算事实。"},
    )

    assert response.status_code == 200
    settlement_tool = next(
        tool for tool in model.calls[0].tools if tool.name == "settlement_details"
    )
    assert set(settlement_tool.input_schema["properties"]) == {
        "year",
        "month",
        "status",
        "company_name",
    }
    evidence = model.calls[1].items[-1].tool_result.evidence
    assert evidence.scope.id == store.id
    assert evidence.source == ["settlement_records"]
    assert evidence.settlement_query_scope.model_dump(mode="json") == {
        "status": None,
        "company_name": None,
    }
    assert evidence.limitations == ["公司结算金额按开票月份归属，没有日粒度。"]
    assert evidence.facts["pending_amount"] == 120
    assert evidence.facts["confirmed_amount"] == 80
    assert {record["status"] for record in evidence.facts["records"]} == {
        "pending",
        "confirmed",
    }
    assert {record["opening_month"] for record in evidence.facts["records"]} == {"2026-07-01"}
    assert "Secret" not in evidence.model_dump_json()
    assert response.json()["content"] == (
        "所有结算公司的待到账公司结算金额合计为 120 欧元；"
        "所有结算公司的已确认公司结算收入合计为 80 欧元。"
    )

    stored = await db_session.scalar(select(AgentEvidence))
    assert stored is not None
    assert stored.payload["result"]["pending_amount"] == 120
    assert stored.payload["result"]["confirmed_amount"] == 80


async def test_current_investigation_restores_context_and_reacquires_changed_evidence(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(username="persistent-agent", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    store.company_settlement_enabled = True
    record = StoreDailyRecord(
        store_id=store.id,
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
    db_session.add_all([AgentSettings(id=1, enabled=True), record])
    await db_session.commit()
    model = PersistentInvestigationModel()

    @asynccontextmanager
    async def session_factory():
        yield db_session

    client._transport.app.state.agent_service = create_agent_service(
        Settings(_env_file=None),
        session_factory,
        native_model=model,
        native_now=lambda: datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc),
        native_evidence_collector=BusinessEvidenceCollector(
            session_factory,
            now=lambda _timezone: datetime(2026, 7, 26, 12, 0),
        ),
    )
    await _login(client, "persistent-agent")

    first = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "调查 2026 年 7 月月度总收入"},
    )

    assert first.status_code == 200
    state = first.json()["conversation"]["state"]
    assert state["investigation_goal"] == "调查 2026 年 7 月月度总收入"
    assert state["confirmed_period"] == {"start": "2026-07-01", "end": "2026-07-26"}
    assert state["confirmed_objects"] == ["月度总收入"]
    assert state["analysis_hypotheses"] == [
        {
            "statement": "经营日变化可能影响月度总收入",
            "status": "unresolved",
            "evidence_references": [],
        }
    ]
    assert state["pending_directions"] == ["检查经营日变化"]
    reference = state["evidence_references"][0]
    assert reference["source"] == ["store_daily_records", "settlement_records"]
    assert reference["queried_at"] == "2026-07-26T12:00:00Z"
    assert reference["data_version"].startswith("sha256:")
    assert reference["use_as_current_fact"] is False

    record.daily_revenue = 360
    await db_session.commit()
    second = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "那现在呢？"},
    )
    restored = await client.get(f"/api/agent/stores/{store.id}/conversation")

    assert second.status_code == 200
    assert second.json()["content"] == "2026 年 7 月月度总收入为 360 欧元。"
    assert restored.status_code == 200
    assert restored.json()["state"]["investigation_goal"] == state["investigation_goal"]
    assert len(restored.json()["state"]["evidence_references"]) == 2
    assert restored.json()["state"]["analysis_hypotheses"] == state["analysis_hypotheses"]
    assert restored.json()["state"]["pending_directions"] == state["pending_directions"]
    assert len(model.calls) == 4
    follow_up_context = model.calls[2].items[0].message
    assert follow_up_context is not None
    assert "调查 2026 年 7 月月度总收入" in follow_up_context.content
    assert reference["reference"] in follow_up_context.content
    assert "240" not in follow_up_context.content

    third = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "每日台账营业额呢？"},
    )

    assert third.status_code == 200
    assert third.json()["content"] == "2026 年 7 月每日台账营业额为 360 欧元。"
    assert third.json()["conversation"]["state"]["confirmed_objects"] == [
        "月度总收入",
        "每日台账营业额",
    ]


@pytest.mark.parametrize(
    "revocation",
    ["inactive_user", "ordinary_role", "inactive_store", "agent_disabled"],
)
async def test_native_tool_execution_rechecks_live_scope_before_business_query(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    revocation: str,
) -> None:
    user = await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma")
    user_id = user.id
    store_id = store.id
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()

    class RevokingModel:
        calls = 0

        async def next_turn(
            self,
            items: Sequence[NativeTranscriptItem],
            *,
            tools: Sequence[NativeToolDefinition],
        ) -> NativeModelTurn:
            del items
            self.calls += 1
            assert {
                "monthly_total_revenue",
                "daily_ledger_revenue",
                "confirmed_settlement_income",
                "operating_days",
            }.issubset(tool.name for tool in tools)
            if revocation in {"inactive_user", "ordinary_role"}:
                fresh_user = await db_session.get(User, user_id)
                assert fresh_user is not None
                if revocation == "inactive_user":
                    fresh_user.is_active = False
                else:
                    fresh_user.role = "user"
            elif revocation == "inactive_store":
                fresh_store = await db_session.get(Store, store_id)
                assert fresh_store is not None
                fresh_store.is_active = False
            else:
                agent_settings = await db_session.get(AgentSettings, 1)
                assert agent_settings is not None
                agent_settings.enabled = False
            await db_session.commit()
            return NativeModelTurn.model_validate(
                {
                    "message": {"role": "assistant", "content": "查询。"},
                    "tool_calls": [
                        {
                            "id": "revoked-call",
                            "name": "monthly_total_revenue",
                            "arguments": {"year": 2026, "month": 7},
                        }
                    ],
                    "signal": "continue",
                }
            )

    @asynccontextmanager
    async def session_factory():
        yield db_session

    model = RevokingModel()
    client._transport.app.state.agent_service = create_agent_service(
        Settings(_env_file=None),
        session_factory,
        native_model=model,
        native_evidence_collector=BusinessEvidenceCollector(session_factory),
    )
    await _login(client, "admin")

    response = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "2026 年 7 月的月度总收入是多少？"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Agent 工具授权已失效"}
    assert model.calls == 1
