import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime

from httpx import AsyncClient

from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.services.agent_chat import AgentChatGraph


class DailyBusinessFlowModel:
    def __init__(self) -> None:
        self.call_number = 0
        self.tool_result: dict[str, object] | None = None

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        tools: Sequence[Mapping[str, object]] | None = None,
    ) -> Mapping[str, object]:
        self.call_number += 1
        if self.call_number == 1:
            return {"content": "需要查询指定日期范围内的完整每日台账经营数据。"}
        if self.call_number == 2:
            assert tools is not None
            analysis_prompt = str(messages[0]["content"])
            assert "营业和提前休息属于经营日" in analysis_prompt
            assert "事件保持 Tool 返回的原始文本" in analysis_prompt
            assert "平均每车收入" in analysis_prompt
            assert "自主决定是否追加查询" in analysis_prompt
            assert "不要求固定结构化报告" in analysis_prompt
            daily_tool = next(
                tool
                for tool in tools
                if tool["function"]["name"] == "get_daily_ledger_data"
            )
            assert daily_tool["function"]["parameters"]["required"] == ["period"]
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "daily-business-call",
                        "type": "function",
                        "function": {
                            "name": "get_daily_ledger_data",
                            "arguments": json.dumps(
                                {"period": "2026-07-13 至 2026-07-15"},
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
        if self.call_number == 3:
            tool_message = next(
                message
                for message in messages
                if message.get("name") == "get_daily_ledger_data"
            )
            self.tool_result = json.loads(str(tool_message["content"]))
            return {"content": "已取得完整每日台账字段和由 Tool 计算的经营指标。"}
        return {"content": "这三天有 2 个经营日，经营日均台账营业额为 105 欧元。"}


class DailyDimensionFlowModel:
    def __init__(self) -> None:
        self.call_number = 0
        self.results: dict[str, dict[str, object]] = {}

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        tools: Sequence[Mapping[str, object]] | None = None,
    ) -> Mapping[str, object]:
        self.call_number += 1
        if self.call_number == 1:
            return {"content": "需要由 Tool 筛选并横向比较每日台账经营维度。"}
        if self.call_number == 2:
            assert tools is not None
            daily_tool = next(
                tool
                for tool in tools
                if tool["function"]["name"] == "get_daily_ledger_data"
            )
            properties = daily_tool["function"]["parameters"]["properties"]
            assert set(properties) == {"period", "filters", "group_by"}
            calls = {
                "combined-filter": {
                    "period": "2026-07-13 至 2026-07-16",
                    "filters": {
                        "operating_status": ["营业", "提前休息"],
                        "weekdays": ["星期一", "星期三"],
                        "recorded_weather": ["晴", "中雨"],
                        "has_event": True,
                    },
                },
                "wash-filter": {
                    "period": "2026-07-13 至 2026-07-16",
                    "filters": {"wash_count_covered": True},
                },
                **{
                    f"group-{dimension}": {
                        "period": "2026-07-13 至 2026-07-16",
                        "group_by": dimension,
                    }
                    for dimension in (
                        "operating_status",
                        "weekday",
                        "recorded_weather",
                        "has_event",
                        "wash_count_coverage",
                    )
                },
            }
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "get_daily_ledger_data",
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                    for call_id, arguments in calls.items()
                ],
            }
        if self.call_number == 3:
            self.results = {
                str(message["tool_call_id"]): json.loads(str(message["content"]))
                for message in messages
                if message.get("name") == "get_daily_ledger_data"
            }
            return {"content": "Tool 已完成各维度筛选和分组。"}
        return {"content": "已按营业状态、星期、天气、事件和洗车数量覆盖完成比较。"}


class InvalidDailyQueryFlowModel:
    def __init__(self) -> None:
        self.call_number = 0
        self.results: list[dict[str, object]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        tools: Sequence[Mapping[str, object]] | None = None,
    ) -> Mapping[str, object]:
        self.call_number += 1
        if self.call_number == 1:
            return {"content": "需要安全校验每日台账查询参数。"}
        if self.call_number == 2:
            invalid_arguments = [
                {"period": "2026-07-20 至 2026-07-21"},
                {
                    "period": "2026-07-13 至 2026-07-15",
                    "filters": {"store_id": 999},
                },
                {
                    "period": "2026-07-13 至 2026-07-15",
                    "group_by": "sql_expression",
                },
            ]
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": f"invalid-{index}",
                        "type": "function",
                        "function": {
                            "name": "get_daily_ledger_data",
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                    for index, arguments in enumerate(invalid_arguments)
                ],
            }
        if self.call_number == 3:
            self.results = [
                json.loads(str(message["content"]))
                for message in messages
                if message.get("name") == "get_daily_ledger_data"
            ]
            return {"content": "无效查询均已安全拒绝。"}
        return {"content": "这些查询条件无效，请修改日期或筛选维度。"}


async def login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": "secret"}
    )
    assert response.status_code == 200


async def test_daily_business_data_is_complete_and_store_scoped_through_http(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    administrator = await user_factory(
        username="daily-business-admin", password="secret", role="admin"
    )
    store = await store_factory(name="每日台账门店", timezone="Europe/Rome")
    store.income_items_enabled = True
    store.wash_count_enabled = True
    other_store = await store_factory(name="另一门店", timezone="Europe/Rome")
    other_store.income_items_enabled = True
    cash = IncomeCategory(
        store_id=store.id,
        name="现金",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    other_data = IncomeCategory(
        store_id=store.id,
        name="其他数据",
        include_in_total=False,
        is_active=True,
        sort_order=1,
    )
    foreign_category = IncomeCategory(
        store_id=other_store.id,
        name="另一门店机密分类",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add_all([cash, other_data, foreign_category])
    await db_session.flush()
    cash_id = cash.id
    other_data_id = other_data.id

    monday = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 13),
        daily_revenue=120,
        income_mode="composed",
        wash_count=4,
        is_open="营业",
        weather="晴",
        activity="  周一促销原文  ",
        created_by=administrator.id,
        updated_by=administrator.id,
    )
    rest = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 14),
        daily_revenue=0,
        income_mode="legacy_total",
        wash_count=None,
        is_open="休息",
        weather=None,
        activity=None,
        created_by=administrator.id,
        updated_by=administrator.id,
    )
    early_close = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 15),
        daily_revenue=90,
        income_mode="composed",
        wash_count=None,
        is_open="提前休息",
        weather="中雨",
        activity="设备故障\n提前关门",
        created_by=administrator.id,
        updated_by=administrator.id,
    )
    foreign = StoreDailyRecord(
        store_id=other_store.id,
        date=date(2026, 7, 13),
        daily_revenue=999,
        income_mode="composed",
        wash_count=1,
        is_open="营业",
        weather="大雪",
        activity="另一门店机密事件",
        created_by=administrator.id,
        updated_by=administrator.id,
    )
    db_session.add_all([monday, rest, early_close, foreign])
    await db_session.flush()
    db_session.add_all(
        [
            DailyIncomeItem(
                record_id=monday.id,
                category_id=cash.id,
                category_name="现金旧名",
                include_in_total=True,
                sort_order=0,
                amount=120,
            ),
            DailyIncomeItem(
                record_id=monday.id,
                category_id=other_data.id,
                category_name="其他数据",
                include_in_total=False,
                sort_order=1,
                amount=20,
            ),
            DailyIncomeItem(
                record_id=early_close.id,
                category_id=cash.id,
                category_name="现金新名",
                include_in_total=True,
                sort_order=0,
                amount=90,
            ),
            DailyIncomeItem(
                record_id=foreign.id,
                category_id=foreign_category.id,
                category_name="另一门店机密分类",
                include_in_total=True,
                sort_order=0,
                amount=999,
            ),
        ]
    )
    await db_session.commit()
    await login(client, "daily-business-admin")
    app = client._transport.app
    app.state.agent_clock = lambda: datetime(2026, 7, 20, 10, tzinfo=UTC)
    model = DailyBusinessFlowModel()
    app.state.agent_chat_graph = AgentChatGraph(model)

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "调查 7 月 13 日到 15 日的每日经营情况"},
    )

    assert response.status_code == 200
    assert model.tool_result == {
        "status": "success",
        "period": {
            "input": "2026-07-13 至 2026-07-15",
            "start": "2026-07-13",
            "end": "2026-07-15",
            "timezone": "Europe/Rome",
        },
        "summary": {
            "record_count": 3,
            "operating_day_count": 2,
            "daily_ledger_revenue": 210,
            "operating_day_average_revenue": 105,
            "wash_count_coverage": {
                "covered_operating_days": 1,
                "operating_days": 2,
                "wash_count": 4,
            },
            "average_revenue_per_wash": 30,
        },
        "records": [
            {
                "date": "2026-07-13",
                "weekday": "星期一",
                "operating_status": "营业",
                "is_operating_day": True,
                "daily_ledger_revenue": 120,
                "income_categories": [
                    {
                            "category_id": cash_id,
                        "category_name": "现金旧名",
                        "include_in_total": True,
                        "amount": 120,
                    },
                    {
                            "category_id": other_data_id,
                        "category_name": "其他数据",
                        "include_in_total": False,
                        "amount": 20,
                    },
                ],
                "wash_count": 4,
                "wash_count_covered": True,
                "recorded_weather": "晴",
                "event": "  周一促销原文  ",
                "has_event": True,
            },
            {
                "date": "2026-07-14",
                "weekday": "星期二",
                "operating_status": "休息",
                "is_operating_day": False,
                "daily_ledger_revenue": 0,
                "income_categories": [],
                "wash_count": None,
                "wash_count_covered": False,
                "recorded_weather": None,
                "event": None,
                "has_event": False,
            },
            {
                "date": "2026-07-15",
                "weekday": "星期三",
                "operating_status": "提前休息",
                "is_operating_day": True,
                "daily_ledger_revenue": 90,
                "income_categories": [
                    {
                        "category_id": cash_id,
                        "category_name": "现金新名",
                        "include_in_total": True,
                        "amount": 90,
                    }
                ],
                "wash_count": None,
                "wash_count_covered": False,
                "recorded_weather": "中雨",
                "event": "设备故障\n提前关门",
                "has_event": True,
            },
        ],
    }
    serialized = json.dumps(model.tool_result, ensure_ascii=False)
    assert "另一门店机密" not in serialized
    assert "sql" not in serialized.lower()


async def test_daily_business_tool_filters_and_groups_business_dimensions_through_http(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    administrator = await user_factory(
        username="daily-dimension-admin", password="secret", role="admin"
    )
    store = await store_factory(name="维度比较门店", timezone="Europe/Rome")
    store.wash_count_enabled = True
    rows = [
        (date(2026, 7, 13), 120, "营业", 4, "晴", "周一事件"),
        (date(2026, 7, 14), 999, "休息", None, None, None),
        (date(2026, 7, 15), 90, "提前休息", None, "中雨", "提前关门"),
        (date(2026, 7, 16), 80, "营业", 2, "晴", None),
    ]
    db_session.add_all(
        [
            StoreDailyRecord(
                store_id=store.id,
                date=record_date,
                daily_revenue=revenue,
                income_mode="legacy_total",
                wash_count=wash_count,
                is_open=status,
                weather=weather,
                activity=event,
                created_by=administrator.id,
                updated_by=administrator.id,
            )
            for record_date, revenue, status, wash_count, weather, event in rows
        ]
    )
    await db_session.commit()
    await login(client, "daily-dimension-admin")
    app = client._transport.app
    app.state.agent_clock = lambda: datetime(2026, 7, 20, 10, tzinfo=UTC)
    model = DailyDimensionFlowModel()
    app.state.agent_chat_graph = AgentChatGraph(model)

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "按状态、星期、天气、事件和洗车数量覆盖比较这几天"},
    )

    assert response.status_code == 200
    combined = model.results["combined-filter"]
    assert combined["query"] == {
        "filters": {
            "operating_status": ["营业", "提前休息"],
            "weekdays": ["星期一", "星期三"],
            "recorded_weather": ["晴", "中雨"],
            "has_event": True,
        },
        "group_by": None,
    }
    assert [record["date"] for record in combined["records"]] == [
        "2026-07-13",
        "2026-07-15",
    ]
    assert combined["summary"]["operating_day_count"] == 2
    assert combined["summary"]["operating_day_average_revenue"] == 105

    wash_filtered = model.results["wash-filter"]
    assert [record["date"] for record in wash_filtered["records"]] == [
        "2026-07-13",
        "2026-07-16",
    ]
    assert wash_filtered["summary"]["average_revenue_per_wash"] == 200 / 6

    status_groups = model.results["group-operating_status"]["groups"]
    assert [(group["value"], group["summary"]["operating_day_count"]) for group in status_groups] == [
        ("营业", 2),
        ("休息", 0),
        ("提前休息", 1),
    ]
    rest_group = status_groups[1]
    assert rest_group["summary"]["operating_day_average_revenue"] is None

    assert [
        group["value"] for group in model.results["group-weekday"]["groups"]
    ] == ["星期一", "星期二", "星期三", "星期四"]
    assert [
        group["summary"]["operating_day_average_revenue"]
        for group in model.results["group-weekday"]["groups"]
    ] == [120, None, 90, 80]
    assert (
        model.results["group-weekday"]["summary"][
            "operating_day_average_revenue"
        ]
        == 290 / 3
    )
    assert [
        group["value"]
        for group in model.results["group-recorded_weather"]["groups"]
    ] == ["中雨", "晴", None]
    assert [
        group["value"] for group in model.results["group-has_event"]["groups"]
    ] == [False, True]
    assert [
        group["value"]
        for group in model.results["group-wash_count_coverage"]["groups"]
    ] == [False, True]


async def test_invalid_daily_business_queries_fail_safely_through_http(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    await user_factory(username="invalid-daily-admin", password="secret", role="admin")
    store = await store_factory(name="参数校验门店", timezone="Europe/Rome")
    await db_session.commit()
    await login(client, "invalid-daily-admin")
    app = client._transport.app
    app.state.agent_clock = lambda: datetime(2026, 7, 20, 10, tzinfo=UTC)
    model = InvalidDailyQueryFlowModel()
    app.state.agent_chat_graph = AgentChatGraph(model)

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "执行这些无效每日台账查询"},
    )

    assert response.status_code == 200
    assert model.results == [
        {"status": "error", "error": "期间结束日期不能晚于门店当地今天"},
        {"status": "error", "error": "每日台账筛选条件包含不支持的字段"},
        {"status": "error", "error": "每日台账分组方式无效"},
    ]
    assert "sql" not in json.dumps(model.results, ensure_ascii=False).lower()
