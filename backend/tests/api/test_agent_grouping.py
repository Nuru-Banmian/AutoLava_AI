from contextlib import asynccontextmanager
from datetime import date, datetime

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.model import FakeModelAdapter
from app.agent.service import AgentService
from app.agent.workflow import AgentTurnWorkflow
from app.models.agent import AgentEvidence
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.operations import AgentSettings


async def _login(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    assert response.status_code == 200


async def test_agent_http_groups_filters_and_daily_extremes_are_bounded(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    other_store = await store_factory(name="Milano", timezone="Europe/Rome")
    carta = IncomeCategory(
        store_id=store.id,
        name="Carta",
        include_in_total=True,
        is_active=True,
        sort_order=1,
    )
    cash = IncomeCategory(
        store_id=store.id,
        name="现金",
        include_in_total=True,
        is_active=True,
        sort_order=2,
    )
    secret = IncomeCategory(
        store_id=other_store.id,
        name="Secret",
        include_in_total=True,
        is_active=True,
        sort_order=1,
    )
    db_session.add_all([carta, cash, secret])
    await db_session.flush()

    record_specs = (
        (date(2026, 7, 1), 100, "营业", "晴", ((carta, 70), (cash, 30))),
        (date(2026, 7, 2), 0, "营业", "多云", ((carta, 0), (cash, 0))),
        (date(2026, 7, 3), 100, "提前休息", "晴", ((carta, 100),)),
        (date(2026, 7, 4), 0, "休息", "晴", ((carta, 0),)),
        (date(2026, 7, 5), 0, "营业", "晴", ((cash, 0),)),
    )
    records: list[StoreDailyRecord] = []
    for target, revenue, status, weather, _ in record_specs:
        record = StoreDailyRecord(
            store_id=store.id,
            date=target,
            daily_revenue=revenue,
            income_mode="composed",
            wash_count=None,
            is_open=status,
            weather=weather,
            weather_auto=weather,
            weather_code=None,
            temperature_max=None,
            temperature_min=None,
            precipitation=None,
            activity=None,
            weather_edited=False,
            scanned=False,
            created_by=admin.id,
            updated_by=admin.id,
        )
        db_session.add(record)
        records.append(record)
    other_record = StoreDailyRecord(
        store_id=other_store.id,
        date=date(2026, 7, 1),
        daily_revenue=9_999,
        income_mode="composed",
        wash_count=None,
        is_open="营业",
        weather="晴",
        weather_auto="晴",
        weather_code=None,
        temperature_max=None,
        temperature_min=None,
        precipitation=None,
        activity=None,
        weather_edited=False,
        scanned=False,
        created_by=admin.id,
        updated_by=admin.id,
    )
    db_session.add(other_record)
    await db_session.flush()
    for record, (_, _, _, _, items) in zip(records, record_specs, strict=True):
        db_session.add_all(
            [
                DailyIncomeItem(
                    record_id=record.id,
                    category_id=category.id,
                    category_name=category.name,
                    include_in_total=True,
                    sort_order=category.sort_order,
                    amount=amount,
                )
                for category, amount in items
            ]
        )
    db_session.add(
        DailyIncomeItem(
            record_id=other_record.id,
            category_id=secret.id,
            category_name=secret.name,
            include_in_total=True,
            sort_order=secret.sort_order,
            amount=9_999,
        )
    )
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()

    grouped_requests = [
        {
            "kind": "business_metrics",
            "metric": (
                "income_category_amount"
                if group_by == "income_category"
                else "daily_ledger_revenue"
            ),
            "group_by": group_by,
        }
        for group_by in (
            "date",
            "calendar_month",
            "calendar_year",
            "income_category",
            "recorded_weather",
            "weekday",
            "operating_status",
        )
    ]
    filtered_request = {
        "kind": "business_metrics",
        "metric": "daily_ledger_revenue",
        "filters": {
            "income_categories": ["  cArTa  "],
            "recorded_weather": ["晴", "多云"],
            "weekdays": ["星期三", "星期五"],
            "operating_statuses": ["营业", "提前休息"],
        },
    }
    plans = [
        {
            "route": "evidence",
            "evidence_plan": {"requests": [request]},
        }
        for request in [
            *grouped_requests,
            filtered_request,
            {
                "kind": "business_metrics",
                "metric": "daily_ledger_revenue",
                "extreme": "highest",
            },
            {
                "kind": "business_metrics",
                "metric": "daily_ledger_revenue",
                "extreme": "lowest",
            },
            {
                "kind": "business_metrics",
                "metric": "daily_ledger_revenue",
                "filters": {"income_categories": ["Cart"]},
            },
        ]
    ]

    @asynccontextmanager
    async def session_factory():
        yield db_session

    model = FakeModelAdapter(
        plans=plans,
        answers=["后端证据摘要优先。"] * 10,
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
    await _login(client)
    store_id = store.id

    expected_groups = {
        "date": [
            ("2026-07-01", 100),
            ("2026-07-02", 0),
            ("2026-07-03", 100),
            ("2026-07-04", 0),
            ("2026-07-05", 0),
        ],
        "calendar_month": [("2026-07", 200)],
        "calendar_year": [("2026", 200)],
        "income_category": [("Carta", 170), ("现金", 30)],
        "recorded_weather": [("多云", 0), ("晴", 200)],
        "weekday": [
            ("星期三", 100),
            ("星期四", 0),
            ("星期五", 100),
            ("星期六", 0),
            ("星期日", 0),
        ],
        "operating_status": [("营业", 100), ("提前休息", 100), ("休息", 0)],
    }
    for group_by in expected_groups:
        response = await client.post(
            f"/api/agent/stores/{store_id}/turn",
            json={"question": f"本月按{group_by}分组。"},
        )
        assert response.status_code == 200
        assert response.json()["route"] == "answer"
        evidence = await db_session.scalar(
            select(AgentEvidence).order_by(AgentEvidence.id.desc())
        )
        assert evidence is not None
        if group_by == "income_category":
            assert [
                (row["category_name"], row["amount"])
                for row in evidence.payload["result"]["categories"]
            ] == expected_groups[group_by]
        else:
            assert evidence.payload["result"]["group_by"] == group_by
            assert [
                (row["label"], row["value"])
                for row in evidence.payload["result"]["rows"]
            ] == expected_groups[group_by]
        assert evidence.payload["current_store"] == {"id": store_id}
        assert "9999" not in str(evidence.payload)
        assert "Secret" not in str(evidence.payload)

    filtered = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "本月 Carta 在晴或多云、星期三或星期五、营业或提前休息的营业额。"},
    )
    print(filtered.json())
    assert filtered.status_code == 200
    assert filtered.json()["conversation"]["state"]["filters"] == {
        "income_categories": ["cArTa"],
        "recorded_weather": ["晴", "多云"],
        "weekdays": ["星期三", "星期五"],
        "operating_statuses": ["营业", "提前休息"],
    }
    filtered_evidence = await db_session.scalar(
        select(AgentEvidence).order_by(AgentEvidence.id.desc())
    )
    assert filtered_evidence is not None
    assert filtered_evidence.payload["filters"] == {
        "income_categories": ["cArTa"],
        "recorded_weather": ["晴", "多云"],
        "weekdays": ["星期三", "星期五"],
        "operating_statuses": ["营业", "提前休息"],
    }
    assert filtered_evidence.payload["result"] == {"daily_ledger_revenue": 200}
    assert "筛选后匹配 2 个每日台账日期" in filtered_evidence.payload["summary"]

    for direction, expected_dates in (
        ("highest", ["2026-07-01", "2026-07-03"]),
        ("lowest", ["2026-07-02", "2026-07-05"]),
    ):
        response = await client.post(
            f"/api/agent/stores/{store_id}/turn",
            json={"question": f"本月{direction}每日台账营业额。"},
        )
        assert response.status_code == 200
        evidence = await db_session.scalar(
            select(AgentEvidence).order_by(AgentEvidence.id.desc())
        )
        assert evidence is not None
        assert evidence.payload["result"]["extreme"] == direction
        assert evidence.payload["result"]["dates"] == expected_dates
        assert evidence.payload["result"]["daily_ledger_revenue"] == (
            100 if direction == "highest" else 0
        )
        assert "2026-07-04" not in evidence.payload["result"]["dates"]

    evidence_count = await db_session.scalar(select(func.count(AgentEvidence.id)))
    unknown = await client.post(
        f"/api/agent/stores/{store_id}/turn",
        json={"question": "本月 Cart 分类的营业额。"},
    )
    assert unknown.status_code == 200
    assert unknown.json()["route"] == "clarify"
    assert "请从候选项中选择" in unknown.json()["content"]
    assert "Carta" in unknown.json()["content"]
    assert "现金" in unknown.json()["content"]
    assert "Secret" not in unknown.json()["content"]
    assert await db_session.scalar(select(func.count(AgentEvidence.id))) == evidence_count
