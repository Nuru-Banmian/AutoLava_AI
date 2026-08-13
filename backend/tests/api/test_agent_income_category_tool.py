import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime

from httpx import AsyncClient

from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.services.agent_chat import AgentChatGraph


class CategoryCompositionFlowModel:
    def __init__(self) -> None:
        self.call_number = 0
        self.catalog: dict[str, object] | None = None
        self.category_result: dict[str, object] | None = None

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        tools: Sequence[Mapping[str, object]] | None = None,
    ) -> Mapping[str, object]:
        self.call_number += 1
        if self.call_number == 1:
            return {"content": "需要先读取当前分类，再按分类 ID 查询历史构成。"}
        if self.call_number == 2:
            assert tools is not None
            assert {tool["function"]["name"] for tool in tools} >= {
                "get_store_data_catalog",
                "get_income_category_history",
            }
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "catalog-call",
                        "type": "function",
                        "function": {
                            "name": "get_store_data_catalog",
                            "arguments": "{}",
                        },
                    }
                ],
            }
        if self.call_number == 3:
            catalog_message = next(
                message
                for message in messages
                if message.get("role") == "tool"
                and message.get("name") == "get_store_data_catalog"
            )
            self.catalog = json.loads(str(catalog_message["content"]))
            categories = self.catalog["income_categories"]
            assert isinstance(categories, list)
            selected_ids = [
                category["id"]
                for category in categories
                if category["name"] in {"现金新名", "线上支付", "其他数据"}
            ]
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "category-history-call",
                        "type": "function",
                        "function": {
                            "name": "get_income_category_history",
                            "arguments": json.dumps(
                                {
                                    "period": "2026-07-01 至 2026-07-31",
                                    "category_ids": selected_ids,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
        if self.call_number == 4:
            result_message = next(
                message
                for message in messages
                if message.get("role") == "tool"
                and message.get("name") == "get_income_category_history"
            )
            self.category_result = json.loads(str(result_message["content"]))
            return {"content": "已取得由 Tool 计算的组合金额和历史口径。"}
        return {
            "content": (
                "现金旧名加线上支付旧名按历史口径计入营业额 120 欧元；其他数据 20 "
                "欧元不计入。另有 70 欧元属于总额记账，无法拆分到分类。"
            )
        }


class SingleCategoryQueryFlowModel:
    def __init__(self, category_id: int, *, analysis: str, answer: str) -> None:
        self.category_id = category_id
        self.analysis = analysis
        self.answer = answer
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
            return {"content": "需要安全校验分类归属，并保留可确认的期间数据。"}
        if self.call_number == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "unmatched-category-call",
                        "type": "function",
                        "function": {
                            "name": "get_income_category_history",
                            "arguments": json.dumps(
                                {
                                    "period": "2026-07-01 至 2026-07-31",
                                    "category_ids": [self.category_id],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
        if self.call_number == 3:
            tool_message = next(
                message for message in messages if message.get("role") == "tool"
            )
            self.tool_result = json.loads(str(tool_message["content"]))
            return {"content": self.analysis}
        return {"content": self.answer}


async def login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": "secret"}
    )
    assert response.status_code == 200


async def test_agent_uses_current_category_ids_and_historical_snapshots_through_http(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    administrator = await user_factory(
        username="category-admin", password="secret", role="admin"
    )
    store = await store_factory(name="分类历史门店")
    store.income_items_enabled = True
    other_store = await store_factory(name="另一门店")
    other_store.income_items_enabled = True
    cash = IncomeCategory(
        store_id=store.id,
        name="现金",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    custom = IncomeCategory(
        store_id=store.id,
        name="线上支付",
        include_in_total=True,
        is_active=True,
        sort_order=1,
    )
    other = IncomeCategory(
        store_id=store.id,
        name="其他数据",
        include_in_total=False,
        is_active=True,
        sort_order=2,
    )
    foreign = IncomeCategory(
        store_id=other_store.id,
        name="另一门店机密分类",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add_all([cash, custom, other, foreign])
    await db_session.flush()
    cash_id = cash.id
    custom_id = custom.id
    other_id = other.id

    categorized = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 10),
        daily_revenue=120,
        income_mode="composed",
        is_open="营业",
        created_by=administrator.id,
        updated_by=administrator.id,
    )
    total_only = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 11),
        daily_revenue=70,
        income_mode="legacy_total",
        is_open="营业",
        created_by=administrator.id,
        updated_by=administrator.id,
    )
    foreign_record = StoreDailyRecord(
        store_id=other_store.id,
        date=date(2026, 7, 10),
        daily_revenue=9999,
        income_mode="composed",
        is_open="营业",
        created_by=administrator.id,
        updated_by=administrator.id,
    )
    db_session.add_all([categorized, total_only, foreign_record])
    await db_session.flush()
    db_session.add_all(
        [
            DailyIncomeItem(
                record_id=categorized.id,
                category_id=cash.id,
                category_name="现金旧名",
                include_in_total=True,
                sort_order=0,
                amount=80,
            ),
            DailyIncomeItem(
                record_id=categorized.id,
                category_id=custom.id,
                category_name="线上支付旧名",
                include_in_total=True,
                sort_order=1,
                amount=40,
            ),
            DailyIncomeItem(
                record_id=categorized.id,
                category_id=other.id,
                category_name="其他数据旧名",
                include_in_total=False,
                sort_order=2,
                amount=20,
            ),
            DailyIncomeItem(
                record_id=foreign_record.id,
                category_id=foreign.id,
                category_name="另一门店机密分类",
                include_in_total=True,
                sort_order=0,
                amount=9999,
            ),
        ]
    )
    await db_session.commit()

    await login(client, administrator.username)
    changed = await client.patch(
        f"/api/admin/income-categories/{cash_id}",
        json={
            "name": "现金新名",
            "include_in_total": False,
            "is_active": False,
        },
    )
    assert changed.status_code == 200

    model = CategoryCompositionFlowModel()
    app = client._transport.app
    app.state.agent_clock = lambda: datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    app.state.agent_chat_graph = AgentChatGraph(model)
    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "今年 7 月现金加线上支付是多少？其他数据是多少？"},
    )

    assert response.status_code == 200
    assert model.call_number == 5
    assert model.catalog is not None
    assert model.catalog["income_categories"] == [
        {
            "id": cash_id,
            "name": "现金新名",
            "include_in_total": False,
            "is_active": False,
        },
        {
            "id": custom_id,
            "name": "线上支付",
            "include_in_total": True,
            "is_active": True,
        },
        {
            "id": other_id,
            "name": "其他数据",
            "include_in_total": False,
            "is_active": True,
        },
    ]
    assert model.category_result == {
        "status": "success",
        "period": {
            "input": "2026-07-01 至 2026-07-31",
            "start": "2026-07-01",
            "end": "2026-07-31",
            "timezone": "Europe/Rome",
        },
        "requested_category_ids": [cash_id, custom_id, other_id],
        "unmatched_category_ids": [],
        "historical_composition": [
            {
                "category_id": cash_id,
                "category_name": "现金旧名",
                "include_in_total": True,
                "amount": 80,
            },
            {
                "category_id": custom_id,
                "category_name": "线上支付旧名",
                "include_in_total": True,
                "amount": 40,
            },
            {
                "category_id": other_id,
                "category_name": "其他数据旧名",
                "include_in_total": False,
                "amount": 20,
            },
        ],
        "selected_categories_total": 140,
        "selected_included_revenue": 120,
        "selected_other_data": 20,
        "categorized_bookkeeping": {
            "record_count": 1,
            "daily_ledger_revenue": 120,
        },
        "total_bookkeeping": {"record_count": 1, "daily_ledger_revenue": 70},
        "period_daily_ledger_revenue": 190,
    }
    assert "9999" not in json.dumps(model.category_result, ensure_ascii=False)
    assert response.json()["message"]["content"].endswith("无法拆分到分类。")


async def test_unmatched_category_keeps_confirmed_total_bookkeeping_through_http(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    administrator = await user_factory(
        username="unmatched-admin", password="secret", role="admin"
    )
    store = await store_factory(name="可确认总额门店")
    other_store = await store_factory(name="不可见分类门店")
    foreign = IncomeCategory(
        store_id=other_store.id,
        name="不可见分类",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add(foreign)
    await db_session.flush()
    foreign_id = foreign.id
    db_session.add(
        StoreDailyRecord(
            store_id=store.id,
            date=date(2026, 7, 20),
            daily_revenue=70,
            income_mode="legacy_total",
            is_open="营业",
            created_by=administrator.id,
            updated_by=administrator.id,
        )
    )
    await db_session.commit()
    await login(client, administrator.username)

    model = SingleCategoryQueryFlowModel(
        foreign_id,
        analysis="分类无匹配，但期间总额记账仍可确认。",
        answer="未找到该分类；可确认这个期间总额记账为 70 欧元。",
    )
    app = client._transport.app
    app.state.agent_clock = lambda: datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    app.state.agent_chat_graph = AgentChatGraph(model)
    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "查询这个分类 7 月的金额"},
    )

    assert response.status_code == 200
    assert model.call_number == 4
    assert model.tool_result == {
        "status": "partial",
        "period": {
            "input": "2026-07-01 至 2026-07-31",
            "start": "2026-07-01",
            "end": "2026-07-31",
            "timezone": "Europe/Rome",
        },
        "requested_category_ids": [foreign_id],
        "unmatched_category_ids": [foreign_id],
        "historical_composition": [],
        "selected_categories_total": 0,
        "selected_included_revenue": 0,
        "selected_other_data": 0,
        "categorized_bookkeeping": {"record_count": 0, "daily_ledger_revenue": 0},
        "total_bookkeeping": {"record_count": 1, "daily_ledger_revenue": 70},
        "period_daily_ledger_revenue": 70,
    }
    assert "不可见分类" not in json.dumps(model.tool_result, ensure_ascii=False)
    assert response.json()["message"]["content"] == (
        "未找到该分类；可确认这个期间总额记账为 70 欧元。"
    )


async def test_current_category_without_history_is_explained_through_http(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    administrator = await user_factory(
        username="no-history-admin", password="secret", role="admin"
    )
    store = await store_factory(name="无历史分类门店")
    category = IncomeCategory(
        store_id=store.id,
        name="会员套餐",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add(category)
    await db_session.flush()
    category_id = category.id
    await db_session.commit()
    await login(client, administrator.username)

    answer = "会员套餐在该期间没有历史数据，不能把它解释为已记录的 0 欧元。"
    model = SingleCategoryQueryFlowModel(
        category_id,
        analysis="分类存在，但所选期间没有历史条目。",
        answer=answer,
    )
    app = client._transport.app
    app.state.agent_clock = lambda: datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    app.state.agent_chat_graph = AgentChatGraph(model)
    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "会员套餐 7 月有多少？"},
    )

    assert response.status_code == 200
    assert model.tool_result is not None
    assert model.tool_result["status"] == "empty"
    assert model.tool_result["requested_category_ids"] == [category_id]
    assert model.tool_result["unmatched_category_ids"] == []
    assert model.tool_result["historical_composition"] == []
    assert response.json()["message"]["content"] == answer
