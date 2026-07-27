from contextlib import asynccontextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.contracts import EvidencePlan
from app.agent.model import FakeModelAdapter
from app.agent.service import AgentService
from app.agent.workflow import AgentTurnWorkflow
from app.models.agent import AgentEvidence
from app.models.ledger import StoreDailyRecord
from app.models.operations import AgentSettings


class NeverEvidenceCollector:
    async def collect(self, plan, context):
        del plan, context
        raise AssertionError("Vague periods must not collect evidence")


async def _login(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    assert response.status_code == 200


def _install_service(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    plans: list[dict[str, object]],
    now: datetime,
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
                now=lambda timezone: now.astimezone(timezone),
            ),
        )
    )
    return model


def _monthly_plan(
    *,
    period: dict[str, object],
    comparison: dict[str, object] | None = None,
) -> dict[str, object]:
    request: dict[str, object] = {
        "kind": "business_metrics",
        "metric": "monthly_total_revenue",
        "period": period,
    }
    if comparison is not None:
        request["comparison"] = comparison
    return {
        "route": "evidence",
        "evidence_plan": {"requests": [request]},
    }


def _record(
    *,
    store_id: int,
    user_id: int,
    on: date,
    revenue: int,
) -> StoreDailyRecord:
    return StoreDailyRecord(
        store_id=store_id,
        date=on,
        daily_revenue=revenue,
        income_mode="legacy_total",
        wash_count=None,
        is_open="营业",
        weather=None,
        weather_auto=None,
        weather_code=None,
        temperature_max=None,
        temperature_min=None,
        precipitation=None,
        activity=None,
        weather_edited=False,
        scanned=False,
        created_by=user_id,
        updated_by=user_id,
    )


@pytest.mark.parametrize(
    ("period", "expected_dates"),
    (
        ({"kind": "current_month"}, ("2026-07-01", "2026-07-26")),
        ({"kind": "previous_month"}, ("2026-06-01", "2026-06-30")),
        ({"kind": "previous_month_to_date"}, ("2026-06-01", "2026-06-26")),
        (
            {"kind": "calendar_month", "year": 2024, "month": 2},
            ("2024-02-01", "2024-02-29"),
        ),
        ({"kind": "calendar_year", "year": 2024}, ("2024-01-01", "2024-12-31")),
        (
            {"kind": "exact_date", "date": "2024-02-29"},
            ("2024-02-29", "2024-02-29"),
        ),
        (
            {
                "kind": "custom_date_range",
                "start": "2025-12-29",
                "end": "2026-01-02",
            },
            ("2025-12-29", "2026-01-02"),
        ),
    ),
)
async def test_agent_http_resolves_bounded_periods_to_exact_dates(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    period: dict[str, object],
    expected_dates: tuple[str, str],
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    _install_service(
        client,
        db_session,
        plans=[_monthly_plan(period=period)],
        now=datetime(2026, 7, 26, 10, 0, tzinfo=ZoneInfo("UTC")),
    )
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "查询准确期间的收入"},
    )

    start, end = expected_dates
    assert response.status_code == 200
    assert response.json()["route"] == "answer"
    assert f"{start} 至 {end}" in response.json()["content"]
    assert response.json()["conversation"]["state"]["confirmed_period"] == {
        "start": start,
        "end": end,
    }


@pytest.mark.parametrize(
    (
        "question",
        "baseline",
        "include_percentage",
        "expected_status",
        "expected_percentage",
    ),
    (
        ("只给金额差", 100, True, "not_requested", None),
        ("不要百分比，只给金额差", 100, True, "not_requested", None),
        ("百分比变化是多少", 100, True, "available", 100.0),
        ("百分比变化是多少", 0, True, "unavailable_zero_baseline", None),
        ("百分比变化是多少", None, True, "unavailable_no_data", None),
    ),
)
async def test_agent_http_applies_comparison_limits(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    question: str,
    baseline: int | None,
    include_percentage: bool,
    expected_status: str,
    expected_percentage: float | None,
) -> None:
    user = await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    db_session.add(AgentSettings(id=1, enabled=True))
    db_session.add(
        _record(
            store_id=store.id,
            user_id=user.id,
            on=date(2026, 7, 10),
            revenue=200,
        )
    )
    if baseline is not None:
        db_session.add(
            _record(
                store_id=store.id,
                user_id=user.id,
                on=date(2026, 6, 10),
                revenue=baseline,
            )
        )
    await db_session.commit()
    _install_service(
        client,
        db_session,
        plans=[
            _monthly_plan(
                period={"kind": "current_month"},
                comparison={
                    "period": {"kind": "previous_month"},
                    "include_percentage": include_percentage,
                },
            )
        ],
        now=datetime(2026, 7, 26, 10, 0, tzinfo=ZoneInfo("UTC")),
    )
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": f"本月与完整上月相比，{question}"},
    )

    assert response.status_code == 200
    assert "2026-07-01 至 2026-07-26" in response.json()["content"]
    assert "2026-06-01 至 2026-06-30" in response.json()["content"]
    evidence = await db_session.scalar(select(AgentEvidence).order_by(AgentEvidence.id.desc()))
    assert evidence is not None
    comparison = evidence.payload["comparison"]
    assert comparison["percentage_status"] == expected_status
    assert comparison["percentage_change"] == expected_percentage
    if baseline is None:
        assert comparison["status"] == "no_data"
        assert "没有历史数据" in response.json()["content"]
    else:
        assert comparison["amount_difference"] == 200 - baseline
        assert "期间长度不同（26 天与 30 天）" in response.json()["content"]
    if expected_status == "not_requested":
        assert "百分比" not in response.json()["content"]
    if expected_status == "unavailable_zero_baseline":
        assert "百分比不可用" in response.json()["content"]
        assert "inf" not in str(evidence.payload).lower()


@pytest.mark.parametrize(
    ("timezone", "expected_dates"),
    (
        ("Europe/Rome", ("2026-03-01", "2026-03-01")),
        ("Pacific/Honolulu", ("2026-02-01", "2026-02-28")),
    ),
)
async def test_agent_http_uses_store_timezone_at_month_boundary(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    timezone: str,
    expected_dates: tuple[str, str],
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name=timezone, timezone=timezone)
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    _install_service(
        client,
        db_session,
        plans=[_monthly_plan(period={"kind": "current_month"})],
        now=datetime(2026, 3, 1, 0, 30, tzinfo=ZoneInfo("UTC")),
    )
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "本月收入"},
    )

    assert response.status_code == 200
    assert f"{expected_dates[0]} 至 {expected_dates[1]}" in response.json()["content"]


async def test_agent_http_caps_previous_month_to_date_at_month_end(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    _install_service(
        client,
        db_session,
        plans=[_monthly_plan(period={"kind": "previous_month_to_date"})],
        now=datetime(2026, 3, 31, 10, 0, tzinfo=ZoneInfo("UTC")),
    )
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "上月同期收入"},
    )

    assert response.status_code == 200
    assert "2026-02-01 至 2026-02-28" in response.json()["content"]


@pytest.mark.parametrize("question", ("那最近呢？", "早些时候收入怎么样？"))
async def test_agent_http_requires_clarification_for_vague_periods(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    question: str,
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma")
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    model = FakeModelAdapter(
        plans=[_monthly_plan(period={"kind": "current_month"})],
        answers=["不应调用模型"],
    )
    client._transport.app.state.agent_service = AgentService(
        AgentTurnWorkflow(
            model=model,
            evidence_collector=NeverEvidenceCollector(),
        )
    )
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": question},
    )

    assert response.status_code == 200
    assert response.json()["route"] == "clarify"
    assert model.total_calls == 0
    assert await db_session.scalar(select(func.count(AgentEvidence.id))) == 0


async def test_agent_http_allows_an_exact_period_when_vague_word_is_negated(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    model = _install_service(
        client,
        db_session,
        plans=[
            _monthly_plan(
                period={
                    "kind": "calendar_month",
                    "year": 2026,
                    "month": 7,
                }
            )
        ],
        now=datetime(2026, 8, 10, 10, 0, tzinfo=ZoneInfo("UTC")),
    )
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "不要查最近，查 2026 年 7 月。"},
    )

    assert response.status_code == 200
    assert response.json()["route"] == "answer"
    assert "2026-07-01 至 2026-07-31" in response.json()["content"]
    assert model.total_calls == 2


def test_period_contract_rejects_out_of_bounds_dates() -> None:
    for period in (
        {"kind": "exact_date", "date": "1999-12-31"},
        {
            "kind": "custom_date_range",
            "start": "2026-01-01",
            "end": "2201-01-01",
        },
    ):
        with pytest.raises(ValueError):
            EvidencePlan.model_validate(
                {"requests": [_monthly_plan(period=period)["evidence_plan"]["requests"][0]]}
            )
