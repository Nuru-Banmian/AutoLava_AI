from collections.abc import Sequence
from datetime import date
import json

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentSystemSettings
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.services.agent_model import ModelResponse, ModelToolCall


async def _login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200


def _tool_results(messages: Sequence[dict[str, object]]) -> list[dict]:
    return [
        json.loads(message["content"])
        for message in messages
        if message["role"] == "tool"
        and "result_id" in json.loads(message["content"])
    ]


def _events(response_text: str) -> list[dict]:
    return [json.loads(line) for line in response_text.splitlines() if line]


class ScriptedPerformanceAdapter:
    def __init__(
        self,
        tool_calls: tuple[ModelToolCall, ...],
        answer: str,
    ) -> None:
        self.tool_calls = tool_calls
        self.answer = answer
        self.step = 0
        self.last_messages: Sequence[dict[str, object]] = ()

    async def respond(self, messages, _tools) -> ModelResponse:
        self.step += 1
        self.last_messages = messages
        if self.step == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="load",
                        name="load_skill",
                        arguments={"name": "business_performance"},
                    ),
                )
            )
        if self.step == 2:
            return ModelResponse(tool_calls=self.tool_calls)
        return ModelResponse(content=self.answer)


def _trend_adapter() -> ScriptedPerformanceAdapter:
    return ScriptedPerformanceAdapter(
        (
            ModelToolCall(
                id="daily",
                name="ledger_revenue_trend",
                arguments={
                    "start": "2026-07-01",
                    "end": "2026-07-03",
                    "bucket": "day",
                },
            ),
            ModelToolCall(
                id="monthly",
                name="ledger_revenue_trend",
                arguments={
                    "start": "2026-06-01",
                    "end": "2026-07-03",
                    "bucket": "month",
                },
            ),
        ),
        "趋势已分析。",
    )


def _composition_adapter() -> ScriptedPerformanceAdapter:
    return ScriptedPerformanceAdapter(
        (
            ModelToolCall(
                id="composition",
                name="income_composition",
                arguments={
                    "start": "2026-07-01",
                    "end": "2026-07-02",
                },
            ),
            ModelToolCall(
                id="zero-composition",
                name="income_composition",
                arguments={
                    "start": "2026-07-03",
                    "end": "2026-07-03",
                },
            ),
        ),
        "分类数据构成已分析。",
    )


def _detail_adapter() -> ScriptedPerformanceAdapter:
    return ScriptedPerformanceAdapter(
        (
            ModelToolCall(
                id="filtered",
                name="daily_ledger_detail",
                arguments={
                    "start": "2026-07-01",
                    "end": "2026-07-03",
                    "operating_statuses": ["营业"],
                    "recorded_weather": "晴",
                    "events_only": True,
                    "event_keyword": "施工",
                    "missing_wash_count": True,
                    "limit": 20,
                    "offset": 0,
                },
            ),
            ModelToolCall(
                id="paged",
                name="daily_ledger_detail",
                arguments={
                    "start": "2026-07-01",
                    "end": "2026-07-03",
                    "limit": 1,
                    "offset": 0,
                },
            ),
        ),
        "每日台账明细已分析。",
    )


def _comparison_adapter() -> ScriptedPerformanceAdapter:
    return ScriptedPerformanceAdapter(
        (
            ModelToolCall(
                id="current",
                name="business_performance_summary",
                arguments={
                    "start": "2026-07-01",
                    "end": "2026-07-03",
                },
            ),
            ModelToolCall(
                id="comparison",
                name="business_performance_summary",
                arguments={
                    "start": "2026-06-01",
                    "end": "2026-06-03",
                },
            ),
        ),
        "两个期间的可比性已分析。",
    )


async def test_agent_returns_daily_and_monthly_ledger_revenue_trends(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="trend-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="趋势门店")
    db_session.add_all(
        (
            AgentSystemSettings(enabled=True),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 6, 30),
                daily_revenue=90,
                is_open="营业",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 1),
                daily_revenue=100,
                is_open="营业",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 2),
                daily_revenue=40,
                is_open="提前休息",
                created_by=admin.id,
                updated_by=admin.id,
            ),
        )
    )
    store_id = store.id
    await db_session.commit()
    adapter = _trend_adapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026-06-01 到 2026-07-03 的营业额趋势"},
    )

    assert response.status_code == 200
    assert '"type":"failed"' not in response.text, response.text
    daily, monthly = _tool_results(adapter.last_messages)
    assert daily["data"] == {
        "bucket": "day",
        "points": [
            {"period": "2026-07-01", "ledger_revenue": "100"},
            {"period": "2026-07-02", "ledger_revenue": "40"},
        ],
    }
    assert monthly["data"] == {
        "bucket": "month",
        "points": [
            {"period": "2026-06", "ledger_revenue": "90"},
            {"period": "2026-07", "ledger_revenue": "140"},
        ],
    }
    assert daily["coverage"] == {
        "range_start": "2026-07-01",
        "range_end": "2026-07-03",
        "requested_days": 3,
        "matching_records": 2,
        "unrecorded_days": 1,
        "complete": False,
        "operating_days": 2,
        "truncated": False,
    }
    assert all(
        "settlement" not in json.dumps(result, ensure_ascii=False).lower()
        for result in (daily, monthly)
    )


async def test_agent_returns_historical_income_and_other_data_composition(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="composition-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="分类门店")
    cash = IncomeCategory(
        store_id=store.id,
        name="现金新称",
        include_in_total=True,
        sort_order=1,
    )
    coupon = IncomeCategory(
        store_id=store.id,
        name="优惠",
        include_in_total=False,
        sort_order=2,
    )
    zero_category = IncomeCategory(
        store_id=store.id,
        name="零额历史分类",
        include_in_total=True,
        sort_order=3,
    )
    db_session.add_all(
        (AgentSystemSettings(enabled=True), cash, coupon, zero_category)
    )
    await db_session.flush()
    first = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 1),
        daily_revenue=1,
        is_open="营业",
        created_by=admin.id,
        updated_by=admin.id,
    )
    second = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 2),
        daily_revenue=2,
        is_open="营业",
        created_by=admin.id,
        updated_by=admin.id,
    )
    third = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 3),
        daily_revenue=0,
        is_open="营业",
        created_by=admin.id,
        updated_by=admin.id,
    )
    db_session.add_all((first, second, third))
    await db_session.flush()
    db_session.add_all(
        (
            DailyIncomeItem(
                record_id=first.id,
                category_id=cash.id,
                category_name="现金旧称",
                include_in_total=True,
                sort_order=1,
                amount=1,
            ),
            DailyIncomeItem(
                record_id=second.id,
                category_id=cash.id,
                category_name="现金新称",
                include_in_total=True,
                sort_order=1,
                amount=2,
            ),
            DailyIncomeItem(
                record_id=second.id,
                category_id=coupon.id,
                category_name="历史优惠",
                include_in_total=False,
                sort_order=2,
                amount=4,
            ),
            DailyIncomeItem(
                record_id=third.id,
                category_id=zero_category.id,
                category_name="零额历史分类",
                include_in_total=True,
                sort_order=3,
                amount=0,
            ),
        )
    )
    store_id = store.id
    cash_id = cash.id
    coupon_id = coupon.id
    zero_category_id = zero_category.id
    await db_session.commit()
    adapter = _composition_adapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026-07-01 到 2026-07-03 的分类记账构成"},
    )

    assert response.status_code == 200
    assert '"type":"failed"' not in response.text, response.text
    assert adapter.step == 3, response.text
    composition, zero_composition = _tool_results(adapter.last_messages)
    assert composition["data"] == {
        "classified_ledger_revenue": "3",
        "income_categories": [
            {
                "category_id": cash_id,
                "category_name": "现金旧称",
                "include_in_ledger_revenue": True,
                "amount": "1",
                "proportion": "33.3",
            },
            {
                "category_id": cash_id,
                "category_name": "现金新称",
                "include_in_ledger_revenue": True,
                "amount": "2",
                "proportion": "66.7",
            },
        ],
        "other_data_total": "4",
        "other_data": [
            {
                "category_id": coupon_id,
                "category_name": "历史优惠",
                "include_in_ledger_revenue": False,
                "amount": "4",
            }
        ],
    }
    assert composition["coverage"] == {
        "range_start": "2026-07-01",
        "range_end": "2026-07-02",
        "requested_days": 2,
        "matching_records": 2,
        "unrecorded_days": 0,
        "complete": True,
        "operating_days": 2,
        "classified_records": 2,
        "truncated": False,
    }
    assert zero_composition["status"] == "success"
    assert zero_composition["data"]["income_categories"] == [
        {
            "category_id": zero_category_id,
            "category_name": "零额历史分类",
            "include_in_ledger_revenue": True,
            "amount": "0",
            "proportion": None,
        }
    ]


async def test_agent_filters_and_bounds_daily_ledger_detail(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="detail-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="明细门店")
    db_session.add_all(
        (
            AgentSystemSettings(enabled=True),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 1),
                daily_revenue=100,
                wash_count=None,
                is_open="营业",
                weather="晴",
                activity="道路施工",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 2),
                daily_revenue=80,
                wash_count=4,
                is_open="提前休息",
                weather="中雨",
                activity="附近施工",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 3),
                daily_revenue=0,
                wash_count=None,
                is_open="休息",
                weather="晴",
                activity=None,
                created_by=admin.id,
                updated_by=admin.id,
            ),
        )
    )
    store_id = store.id
    await db_session.commit()
    adapter = _detail_adapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "查询 2026-07-01 到 2026-07-03 的每日台账明细"},
    )

    assert response.status_code == 200
    assert '"type":"failed"' not in response.text, response.text
    filtered, paged = _tool_results(adapter.last_messages)
    assert filtered["data"]["records"] == [
        {
            "date": "2026-07-01",
            "ledger_revenue": "100",
            "operating_status": "营业",
            "wash_count": None,
            "recorded_weather": "晴",
            "event": "道路施工",
        }
    ]
    assert filtered["coverage"] == {
        "range_start": "2026-07-01",
        "range_end": "2026-07-03",
        "matching_records": 1,
        "returned_records": 1,
        "missing_wash_count_days": 1,
        "truncated": False,
        "next_offset": None,
    }
    assert len(paged["data"]["records"]) == 1
    assert paged["coverage"]["matching_records"] == 3
    assert paged["coverage"]["returned_records"] == 1
    assert paged["coverage"]["truncated"] is True
    assert paged["coverage"]["next_offset"] == 1
    cards = [
        event["card"]
        for event in _events(response.text)
        if event["type"] == "investigation_card"
    ]
    assert cards[0]["filters"] == [
        "营业状态：营业",
        "记录天气：晴",
        "仅有事件",
        "已应用事件关键词筛选",
        "洗车数量：缺失",
    ]
    assert all(
        forbidden not in json.dumps(cards, ensure_ascii=False)
        for forbidden in ("100", "道路施工", "result-")
    )


async def test_agent_exposes_period_completeness_and_uses_only_valid_wash_counts(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="comparison-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="期间对比门店")
    db_session.add_all(
        (
            AgentSystemSettings(enabled=True),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 6, 1),
                daily_revenue=60,
                income_mode="legacy_total",
                wash_count=2,
                is_open="营业",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 1),
                daily_revenue=100,
                income_mode="composed",
                wash_count=2,
                is_open="营业",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 2),
                daily_revenue=50,
                income_mode="composed",
                wash_count=0,
                is_open="提前休息",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 3),
                daily_revenue=0,
                income_mode="composed",
                wash_count=None,
                is_open="休息",
                created_by=admin.id,
                updated_by=admin.id,
            ),
        )
    )
    store_id = store.id
    await db_session.commit()
    adapter = _comparison_adapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "对比 2026-06-01 到 2026-06-03 与 2026-07-01 到 2026-07-03 的经营表现"},
    )

    assert response.status_code == 200
    assert '"type":"failed"' not in response.text, response.text
    current, comparison = _tool_results(adapter.last_messages)
    assert current["coverage"]["requested_days"] == 3
    assert current["coverage"]["unrecorded_days"] == 0
    assert current["coverage"]["complete"] is True
    assert current["data"]["wash_count"] == "2"
    assert current["data"]["average_revenue_per_wash"] == "75"
    assert current["coverage"]["missing_wash_count_days"] == 0
    assert current["coverage"]["business_basis"] == {
        "income_modes": ["composed"],
        "wash_count_enabled": True,
        "company_settlement_included": False,
    }
    assert comparison["coverage"]["requested_days"] == 3
    assert comparison["coverage"]["unrecorded_days"] == 2
    assert comparison["coverage"]["complete"] is False
    assert comparison["coverage"]["business_basis"]["income_modes"] == [
        "legacy_total"
    ]
    loaded_skill = next(
        json.loads(message["content"])
        for message in adapter.last_messages
        if message["role"] == "tool"
        and "instructions" in json.loads(message["content"])
    )
    assert "范围长度、完整度或业务口径不一致" in loaded_skill["instructions"]
    assert "不得静默替换" in loaded_skill["instructions"]
    assert "相同长度或完整自然月" in loaded_skill["instructions"]
    assert "业务口径" in loaded_skill["instructions"]
    assert "截断到一位小数" in loaded_skill["instructions"]
    assert "零比较基数" in loaded_skill["instructions"]
