from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.native import (
    FakeNativeToolModel,
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
    model = FakeNativeToolModel(
        turns=[
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
            },
            {
                "message": {"role": "assistant", "content": expected_answer},
                "signal": "end",
            },
        ],
        before_turn=assert_model_runs_without_sqlite_transaction,
    )
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
            assert [tool.name for tool in tools] == [
                "monthly_total_revenue",
                "daily_ledger_revenue",
                "confirmed_settlement_income",
                "operating_days",
            ]
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
