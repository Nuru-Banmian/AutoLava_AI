from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.native import FakeNativeToolModel, NativeToolAgentService
from app.core.config import get_settings
from app.models.agent import AgentEvidence
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

    @asynccontextmanager
    async def session_factory():
        yield db_session

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
        ]
    )
    client._transport.app.state.agent_service = NativeToolAgentService(
        model=model,
        evidence_collector=BusinessEvidenceCollector(
            session_factory,
            now=lambda _timezone: datetime(2026, 7, 26, 12, 0),
        ),
        now=lambda: datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc),
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
