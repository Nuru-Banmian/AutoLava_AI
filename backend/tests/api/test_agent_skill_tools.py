import json
from collections.abc import Mapping, Sequence
from datetime import date

from httpx import AsyncClient

from app.models.ledger import IncomeCategory, StoreDailyRecord
from app.services.agent_chat import AgentChatGraph
from app.services.agent_tools import AgentTool, AgentToolRegistry


class CatalogFlowModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        tools: Sequence[Mapping[str, object]] | None = None,
    ) -> Mapping[str, object]:
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "tools": [dict(tool) for tool in tools] if tools is not None else None,
            }
        )
        call_number = len(self.calls)
        if call_number == 1:
            return {"content": "用户需要当前门店的数据目录。"}
        if call_number == 2:
            assert tools is not None
            catalog_tool = next(
                tool for tool in tools if tool["function"]["name"] == "get_store_data_catalog"
            )
            assert catalog_tool["function"]["parameters"] == {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
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

        tool_message = next(message for message in messages if message["role"] == "tool")
        assert tool_message["tool_call_id"] == "catalog-call"
        catalog = json.loads(str(tool_message["content"]))
        assert catalog["store"] == {"name": "授权门店", "timezone": "Europe/Rome"}
        assert catalog["bookkeeping"] == {
            "mode": "categorized",
            "wash_count_enabled": True,
            "company_settlement_enabled": False,
            "revenue_formula": "营业额 = 现金；\u201c其他数据\u201d只记录，不计入营业额",
        }
        assert catalog["income_categories"] == [
            {
                "name": "现金",
                "include_in_total": True,
                "is_active": True,
            },
            {
                "name": "其他数据",
                "include_in_total": False,
                "is_active": True,
            },
        ]
        assert catalog["data_coverage"]["daily_records"] == {
            "record_count": 1,
            "start_date": "2026-08-01",
            "end_date": "2026-08-01",
        }
        assert "另一门店机密分类" not in str(tool_message["content"])
        return {"content": "当前门店采用分类记账，现金计入营业额，其他数据不计入。"}


class IncrementalToolModel:
    def __init__(self) -> None:
        self.call_number = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        tools: Sequence[Mapping[str, object]] | None = None,
    ) -> Mapping[str, object]:
        self.call_number += 1
        if self.call_number == 1:
            return {"content": "需要调用新增工具。"}
        if self.call_number == 2:
            assert tools is not None
            assert [tool["function"]["name"] for tool in tools] == ["new_read_tool"]
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "new-tool-call",
                        "type": "function",
                        "function": {"name": "new_read_tool", "arguments": "{}"},
                    }
                ],
            }
        tool_message = next(message for message in messages if message["role"] == "tool")
        assert json.loads(str(tool_message["content"])) == {"store_name": "扩展门店"}
        return {"content": "新增工具已执行。"}


async def login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret"},
    )
    assert response.status_code == 200


async def test_three_node_agent_uses_the_authorized_store_catalog_through_http(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    administrator = await user_factory(
        username="administrator", password="secret", role="admin"
    )
    authorized_store = await store_factory(name="授权门店")
    authorized_store.income_items_enabled = True
    other_store = await store_factory(name="另一门店")
    other_store.income_items_enabled = True
    db_session.add_all(
        [
            IncomeCategory(
                store_id=authorized_store.id,
                name="现金",
                include_in_total=True,
                is_active=True,
                sort_order=0,
            ),
            IncomeCategory(
                store_id=authorized_store.id,
                name="其他数据",
                include_in_total=False,
                is_active=True,
                sort_order=1,
            ),
            IncomeCategory(
                store_id=other_store.id,
                name="另一门店机密分类",
                include_in_total=True,
                is_active=True,
                sort_order=0,
            ),
            StoreDailyRecord(
                store_id=authorized_store.id,
                date=date(2026, 8, 1),
                daily_revenue=15000,
                income_mode="composed",
                wash_count=10,
                is_open="营业",
                created_by=administrator.id,
                updated_by=administrator.id,
            ),
        ]
    )
    await db_session.commit()
    await login(client, "administrator")
    model = CatalogFlowModel()
    client._transport.app.state.agent_chat_graph = AgentChatGraph(model)

    response = await client.post(
        f"/api/agent/stores/{authorized_store.id}/messages",
        json={"content": "这个门店目前有哪些经营数据？"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": {
            "role": "assistant",
            "content": "当前门店采用分类记账，现金计入营业额，其他数据不计入。",
        }
    }
    assert len(model.calls) == 3
    system_prompts = [call["messages"][0]["content"] for call in model.calls]
    assert "理解 Agent" in system_prompts[0]
    assert "分析 Agent" in system_prompts[1]
    assert "回答 Agent" in system_prompts[2]


async def test_a_registered_tool_is_available_without_changing_the_three_node_graph(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    await user_factory(username="administrator", password="secret", role="admin")
    store = await store_factory(name="扩展门店")
    await db_session.commit()
    await login(client, "administrator")

    async def new_read_tool(context, arguments):
        assert arguments == {}
        return {"store_name": context.store.name}

    registry = AgentToolRegistry(
        [
            AgentTool(
                name="new_read_tool",
                description="用于验证增量注册的只读工具。",
                parameters={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=new_read_tool,
            )
        ]
    )
    model = IncrementalToolModel()
    client._transport.app.state.agent_chat_graph = AgentChatGraph(
        model, tool_registry=registry
    )

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "调用新增工具"},
    )

    assert response.status_code == 200
    assert response.json()["message"]["content"] == "新增工具已执行。"
    assert model.call_number == 3
