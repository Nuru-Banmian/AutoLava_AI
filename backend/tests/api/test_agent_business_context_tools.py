from collections.abc import Sequence
from datetime import date
import json

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentSystemSettings
from app.models.ledger import StoreDailyRecord
from app.services.agent_model import ModelResponse, ModelToolCall


class BusinessContextAdapter:
    def __init__(self) -> None:
        self.step = 0
        self.last_messages: Sequence[dict[str, object]] = ()

    async def respond(self, messages, _tools) -> ModelResponse:
        self.step += 1
        self.last_messages = messages
        if self.step == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="load-context",
                        name="load_skill",
                        arguments={"name": "business_context"},
                    ),
                )
            )
        if self.step == 2:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="weekday-groups",
                        name="business_context_group",
                        arguments={
                            "start": "2026-07-06",
                            "end": "2026-07-09",
                            "dimension": "weekday",
                        },
                    ),
                    ModelToolCall(
                        id="weather-groups",
                        name="business_context_group",
                        arguments={
                            "start": "2026-07-06",
                            "end": "2026-07-09",
                            "dimension": "recorded_weather",
                        },
                    ),
                )
            )
        if self.step == 3:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="event-detail",
                        name="daily_ledger_detail",
                        arguments={
                            "start": "2026-07-06",
                            "end": "2026-07-09",
                            "events_only": True,
                            "limit": 20,
                            "offset": 0,
                        },
                    ),
                )
            )
        return ModelResponse(
            content=(
                "这些记录显示星期、记录天气和经营表现之间的相关性，不能据此认定因果。"
                "事件原文“学校活动且附近施工”在本次调查中可同时临时归为"
                "节庆活动、道路施工，并标记门店具体标识“学校”；"
                "“特殊情况”无法可靠分类，标记为待归类。"
                "记录天气缺失 1 个经营日，因此天气结论强度有限。"
            )
        )


class BusinessContextComparisonAdapter:
    def __init__(self) -> None:
        self.step = 0
        self.last_messages: Sequence[dict[str, object]] = ()

    async def respond(self, messages, _tools) -> ModelResponse:
        self.step += 1
        self.last_messages = messages
        if self.step == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="load-context-comparison",
                        name="load_skill",
                        arguments={"name": "business_context"},
                    ),
                )
            )
        if self.step == 2:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="compare-context",
                        name="business_context_comparison",
                        arguments={
                            "period_a": {
                                "start": "2026-07-06",
                                "end": "2026-07-07",
                            },
                            "period_b": {
                                "start": "2026-07-08",
                                "end": "2026-07-09",
                            },
                        },
                    ),
                )
            )
        return ModelResponse(
            content=(
                "前一期间营业额较高与其经营日更多、记录天气和事件分布不同"
                "存在相关性，但这些记录不足以证明因果关系。"
            )
        )


async def _login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200


def _tool_payloads(
    messages: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        json.loads(message["content"])
        for message in messages
        if message["role"] == "tool"
    ]


async def test_agent_groups_operating_days_and_investigates_original_events(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="context-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="经营背景门店")
    db_session.add_all(
        (
            AgentSystemSettings(enabled=True),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 6),
                daily_revenue=100,
                is_open="营业",
                weather="晴",
                activity="学校活动且附近施工",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 7),
                daily_revenue=50,
                is_open="提前休息",
                weather="中雨",
                activity="特殊情况",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 8),
                daily_revenue=0,
                is_open="休息",
                weather="晴",
                activity="休息日事件",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 9),
                daily_revenue=70,
                is_open="营业",
                weather=None,
                activity=None,
                created_by=admin.id,
                updated_by=admin.id,
            ),
        )
    )
    store_id = store.id
    await db_session.commit()
    adapter = BusinessContextAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={
            "content": (
                "分析 2026-07-06 到 2026-07-09 的每日台账营业额与"
                "经营背景关联"
            )
        },
    )

    assert response.status_code == 200
    assert '"type":"failed"' not in response.text, response.text
    payloads = _tool_payloads(adapter.last_messages)
    skill = next(payload for payload in payloads if "instructions" in payload)
    weekday, weather = [
        payload
        for payload in payloads
        if payload.get("data", {}).get("dimension")
        in {"weekday", "recorded_weather"}
    ]
    detail = next(
        payload
        for payload in payloads
        if "records" in payload.get("data", {})
    )

    assert weekday["data"] == {
        "dimension": "weekday",
        "groups": [
            {
                "key": "1",
                "label": "星期一",
                "operating_days": 1,
                "ledger_revenue": "100",
                "operating_day_average_ledger_revenue": "100",
            },
            {
                "key": "2",
                "label": "星期二",
                "operating_days": 1,
                "ledger_revenue": "50",
                "operating_day_average_ledger_revenue": "50",
            },
            {
                "key": "4",
                "label": "星期四",
                "operating_days": 1,
                "ledger_revenue": "70",
                "operating_day_average_ledger_revenue": "70",
            },
        ],
    }
    assert weather["data"] == {
        "dimension": "recorded_weather",
        "groups": [
            {
                "key": "中雨",
                "label": "中雨",
                "operating_days": 1,
                "ledger_revenue": "50",
                "operating_day_average_ledger_revenue": "50",
            },
            {
                "key": "晴",
                "label": "晴",
                "operating_days": 1,
                "ledger_revenue": "100",
                "operating_day_average_ledger_revenue": "100",
            },
        ],
    }
    assert weekday["coverage"]["operating_days"] == 3
    assert weather["coverage"]["operating_days"] == 3
    assert weather["coverage"]["missing_dimension_days"] == 1
    assert detail["data"]["records"][0]["event"] == "学校活动且附近施工"
    assert detail["data"]["records"][1]["event"] == "特殊情况"
    assert detail["data"]["records"][2]["event"] == "休息日事件"

    instructions = skill["instructions"]
    for requirement in (
        "为什么会这样",
        "business_context_comparison",
        "最近一次对比",
        "经营日差异",
        "原始事件文本",
        "多个",
        "门店具体标识",
        "待归类",
        "不写回",
        "相关性",
        "覆盖",
        "公司结算收入没有日粒度",
    ):
        assert requirement in instructions

    cards = [
        json.loads(line)["card"]
        for line in response.text.splitlines()
        if line and json.loads(line)["type"] == "investigation_card"
    ]
    assert cards[0]["filters"] == ["分组维度：星期"]
    assert cards[1]["filters"] == ["分组维度：记录天气"]
    assert all(
        forbidden not in json.dumps(cards, ensure_ascii=False)
        for forbidden in ("学校活动", "道路施工", "待归类")
    )
    assert all(
        phrase in response.text
        for phrase in (
            "相关性",
            "不能据此认定因果",
            "可同时临时归为",
            "待归类",
            "结论强度有限",
        )
    )


async def test_agent_compares_two_period_business_context_in_one_tool_call(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="context-comparison-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="经营差异背景门店")
    db_session.add_all(
        (
            AgentSystemSettings(enabled=True),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 6),
                daily_revenue=100,
                is_open="营业",
                weather="晴",
                activity="学校活动",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 7),
                daily_revenue=50,
                is_open="提前休息",
                weather="中雨",
                activity=None,
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 8),
                daily_revenue=0,
                is_open="休息",
                weather="晴",
                activity=None,
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 9),
                daily_revenue=70,
                is_open="营业",
                weather=None,
                activity="附近施工",
                created_by=admin.id,
                updated_by=admin.id,
            ),
        )
    )
    store_id = store.id
    await db_session.commit()
    adapter = BusinessContextComparisonAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "刚才两个期间营业额为什么会这样？"},
    )

    assert response.status_code == 200
    assert '"type":"failed"' not in response.text, response.text
    comparison = next(
        payload
        for payload in _tool_payloads(adapter.last_messages)
        if "periods" in payload.get("data", {})
    )
    period_a = comparison["data"]["periods"]["period_a"]
    period_b = comparison["data"]["periods"]["period_b"]
    assert period_a["performance"]["ledger_revenue"] == "150"
    assert period_b["performance"]["ledger_revenue"] == "70"
    assert period_a["performance"]["operating_days"] == 2
    assert period_b["performance"]["operating_days"] == 1
    assert period_a["events"][0]["event"] == "学校活动"
    assert period_b["events"][0]["event"] == "附近施工"
    assert period_b["coverage"]["weather"]["missing_dimension_days"] == 1
    assert adapter.step == 3
