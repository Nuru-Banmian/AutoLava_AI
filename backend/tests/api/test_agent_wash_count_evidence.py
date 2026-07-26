from contextlib import asynccontextmanager
from datetime import date, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.model import FakeModelAdapter
from app.agent.service import AgentService
from app.agent.workflow import AgentTurnWorkflow
from app.models.agent import AgentEvidence
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.operations import AgentSettings
from app.models.settlement import SettlementCompany, SettlementRecord


async def _login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret"},
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("scenario", "metric"),
    (
        ("disabled", "wash_count"),
        ("partial_coverage", "average_revenue_per_car"),
        ("all_zero", "average_revenue_per_car"),
        ("complete_average", "average_revenue_per_car"),
        ("no_records", "average_revenue_per_car"),
        ("missing_weather", "wash_count"),
        ("category_mismatch", "wash_count"),
    ),
)
async def test_wash_count_and_completeness_http_gold_paths(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    scenario: str,
    metric: str,
) -> None:
    user = await user_factory(username="wash-admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    store_id = store.id
    store.wash_count_enabled = scenario != "disabled"
    records: list[StoreDailyRecord] = []
    if scenario != "no_records":
        records.append(
            StoreDailyRecord(
                store_id=store_id,
                date=date(2026, 7, 1),
                daily_revenue=120,
                income_mode=(
                    "composed" if scenario == "category_mismatch" else "legacy_total"
                ),
                wash_count=0 if scenario == "all_zero" else 4,
                is_open="营业",
                weather=None if scenario == "missing_weather" else "晴",
                created_by=user.id,
                updated_by=user.id,
            )
        )
    if scenario in {"partial_coverage", "all_zero"}:
        records.append(
            StoreDailyRecord(
                store_id=store_id,
                date=date(2026, 7, 2),
                daily_revenue=80,
                income_mode="legacy_total",
                wash_count=0 if scenario == "all_zero" else None,
                is_open="提前休息",
                weather="多云",
                created_by=user.id,
                updated_by=user.id,
            )
        )
    db_session.add_all(records)
    if scenario == "category_mismatch":
        category = IncomeCategory(
            store_id=store_id,
            name="现金",
            include_in_total=True,
            is_active=True,
            sort_order=1,
        )
        db_session.add(category)
        await db_session.flush()
        db_session.add(
            DailyIncomeItem(
                record_id=records[0].id,
                category_id=category.id,
                category_name="现金",
                include_in_total=True,
                sort_order=1,
                amount=90,
            )
        )
    if scenario == "complete_average":
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
        db_session.add(
            SettlementRecord(
                store_id=store_id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=999,
                status="confirmed",
                created_by=user.id,
                updated_by=user.id,
            )
        )
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()

    @asynccontextmanager
    async def session_factory():
        yield db_session

    model = FakeModelAdapter(
        plans=[
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [{"kind": "business_metrics", "metric": metric}]
                },
            }
        ],
        answers=["按后端证据回答。"],
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
    await _login(client, "wash-admin")

    response = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": f"场景 {scenario}"},
    )

    assert response.status_code == 200
    assert response.json()["route"] == "answer"
    evidence = await db_session.scalar(select(AgentEvidence))
    assert evidence is not None
    payload = evidence.payload
    completeness = payload["completeness"]
    if scenario == "disabled":
        assert payload["result"] == {"available": False, "wash_count": None}
        assert completeness["wash_count_enabled"] is False
    elif scenario == "partial_coverage":
        assert payload["result"] == {
            "available": False,
            "daily_ledger_revenue": None,
            "wash_count": None,
            "average_revenue_per_car": None,
        }
        assert completeness["wash_count_coverage_percent"] == 50
        assert completeness["wash_count_missing_dates"] == ["2026-07-02"]
    elif scenario == "all_zero":
        assert payload["result"] == {
            "available": False,
            "daily_ledger_revenue": 200,
            "wash_count": 0,
            "average_revenue_per_car": None,
        }
        assert completeness["wash_count_sufficient"] is True
    elif scenario == "complete_average":
        assert payload["result"] == {
            "available": True,
            "daily_ledger_revenue": 120,
            "wash_count": 4,
            "average_revenue_per_car": 30,
        }
    elif scenario == "no_records":
        assert payload["result"]["available"] is False
        assert completeness["wash_count_coverage_percent"] is None
        assert len(completeness["unrecorded_dates"]) == 26
        assert any("不推断记录起始日期" in warning for warning in payload["warnings"])
    elif scenario == "missing_weather":
        assert payload["result"] == {"available": True, "wash_count": 4}
        assert completeness["missing_weather_dates"] == ["2026-07-01"]
    else:
        assert payload["result"] == {"available": True, "wash_count": 4}
        assert completeness["category_total_mismatches"] == [
            {
                "date": "2026-07-01",
                "daily_ledger_revenue": 120,
                "included_category_amount": 90,
            }
        ]


async def test_wash_count_http_gold_path_recovers_history_after_reenabling(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(username="reenable-admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    store_id = store.id
    store.wash_count_enabled = False
    db_session.add(
        StoreDailyRecord(
            store_id=store_id,
            date=date(2026, 7, 1),
            daily_revenue=120,
            income_mode="legacy_total",
            wash_count=6,
            is_open="营业",
            weather="晴",
            created_by=user.id,
            updated_by=user.id,
        )
    )
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()

    @asynccontextmanager
    async def session_factory():
        yield db_session

    model = FakeModelAdapter(
        plans=[
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [{"kind": "business_metrics", "metric": "wash_count"}]
                },
            },
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [{"kind": "business_metrics", "metric": "wash_count"}]
                },
            },
        ],
        answers=["关闭时不可用。", "重新开启后恢复历史数据。"],
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
    await _login(client, "reenable-admin")

    disabled = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "本月洗车数量是多少？"},
    )
    enabled = await client.patch(
        f"/api/admin/stores/{store_id}",
        json={"wash_count_enabled": True},
    )
    reenabled = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "重新开启后本月洗车数量是多少？"},
    )

    assert disabled.status_code == 200
    assert enabled.status_code == 200
    assert reenabled.status_code == 200
    evidence = list(
        await db_session.scalars(select(AgentEvidence).order_by(AgentEvidence.id))
    )
    assert evidence[0].payload["result"] == {"available": False, "wash_count": None}
    assert evidence[1].payload["result"] == {"available": True, "wash_count": 6}
