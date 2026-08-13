import json
from collections.abc import Mapping, Sequence
from datetime import date

import pytest
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
        assert all(
            isinstance(category["id"], int)
            for category in catalog["income_categories"]
        )
        assert [
            {key: value for key, value in category.items() if key != "id"}
            for category in catalog["income_categories"]
        ] == [
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


class RecoveringBusinessToolModel:
    def __init__(
        self,
        understanding_marker: str = "STORE_DATA_REQUIRED",
        store_name: str = "协议恢复门店",
    ) -> None:
        self.call_number = 0
        self.understanding_marker = understanding_marker
        self.store_name = store_name

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        tools: Sequence[Mapping[str, object]] | None = None,
    ) -> Mapping[str, object]:
        self.call_number += 1
        if self.call_number == 1:
            return {
                "content": (
                    f"{self.understanding_marker}\n"
                    "用户询问当前门店本周营业额。"
                )
            }
        if self.call_number == 2:
            assert tools is not None
            return {"content": "无需工具"}
        if self.call_number == 3:
            if tools is None:
                return {"content": "不客气，很高兴能帮到您！"}
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "recovered-tool-call",
                        "type": "function",
                        "function": {"name": "new_read_tool", "arguments": "{}"},
                    }
                ],
            }
        if self.call_number == 4:
            tool_message = next(
                message for message in messages if message["role"] == "tool"
            )
            assert json.loads(str(tool_message["content"])) == {
                "store_name": self.store_name
            }
            return {"content": "已经取得当前门店数据。"}
        return {"content": f"{self.store_name}的本周营业额数据已取得。"}


class RefusingBusinessToolModel:
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
            return {
                "content": "STORE_DATA_REQUIRED\n用户询问当前门店本周营业额。"
            }
        assert tools is not None
        return {"content": "无需工具"}


class RecoveringAnswerModel:
    def __init__(self, first_answer: str) -> None:
        self.call_number = 0
        self.first_answer = first_answer

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        tools: Sequence[Mapping[str, object]] | None = None,
    ) -> Mapping[str, object]:
        self.call_number += 1
        if self.call_number == 1:
            return {"content": "STORE_DATA_REQUIRED\n用户需要星期维度分析。"}
        if self.call_number == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "weekday-tool-call",
                        "type": "function",
                        "function": {"name": "new_read_tool", "arguments": "{}"},
                    }
                ],
            }
        if self.call_number == 3:
            return {"content": "星期数据已经取得。"}
        if self.call_number == 4:
            assert tools is None
            assert any(message["role"] == "tool" for message in messages)
            return {"content": self.first_answer}
        assert tools is None
        assert "必须直接使用已有 Tool Messages" in str(messages[-1]["content"])
        return {"content": "星期一的经营日平均营业额为 120 欧元。"}


class FailingToolModel:
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
            return {"content": "STORE_DATA_REQUIRED\n用户需要门店数据。"}
        if self.call_number == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "failing-tool-call",
                        "type": "function",
                        "function": {"name": "failing_tool", "arguments": "{}"},
                    }
                ],
            }
        if self.call_number == 3:
            tool_message = next(
                message for message in messages if message["role"] == "tool"
            )
            assert json.loads(str(tool_message["content"])) == {
                "error": "工具暂时不可用"
            }
            return {"content": "工具未能返回数据。"}
        return {"content": "暂时无法取得门店数据，请稍后重试。"}


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
    assert len(model.calls) == 4
    system_prompts = [call["messages"][0]["content"] for call in model.calls]
    assert "理解 Agent" in system_prompts[0]
    assert "分析 Agent" in system_prompts[1]
    assert "分析 Agent" in system_prompts[2]
    assert "回答 Agent" in system_prompts[3]


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
    assert model.call_number == 4


async def test_business_question_recovers_when_analysis_initially_skips_tools(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    await user_factory(username="administrator", password="secret", role="admin")
    store = await store_factory(name="协议恢复门店")
    await db_session.commit()
    await login(client, "administrator")

    async def new_read_tool(context, arguments):
        assert arguments == {}
        return {"store_name": context.store.name}

    registry = AgentToolRegistry(
        [
            AgentTool(
                name="new_read_tool",
                description="读取当前门店数据。",
                parameters={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=new_read_tool,
            )
        ]
    )
    model = RecoveringBusinessToolModel()
    client._transport.app.state.agent_chat_graph = AgentChatGraph(
        model, tool_registry=registry
    )

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "这周的营业额是多少？"},
    )

    assert response.status_code == 200
    assert response.json()["message"]["content"] == (
        "协议恢复门店的本周营业额数据已取得。"
    )
    assert model.call_number == 5


async def test_explicit_business_question_overrides_a_model_no_data_misclassification(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    await user_factory(username="administrator", password="secret", role="admin")
    store = await store_factory(name="误分类恢复门店")
    await db_session.commit()
    await login(client, "administrator")

    async def new_read_tool(context, arguments):
        assert arguments == {}
        return {"store_name": context.store.name}

    registry = AgentToolRegistry(
        [
            AgentTool(
                name="new_read_tool",
                description="读取当前门店数据。",
                parameters={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=new_read_tool,
            )
        ]
    )
    model = RecoveringBusinessToolModel(
        "NO_STORE_DATA_REQUIRED", store_name="误分类恢复门店"
    )
    client._transport.app.state.agent_chat_graph = AgentChatGraph(
        model, tool_registry=registry
    )

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "这周自助加自动一共多少？"},
    )

    assert response.status_code == 200
    assert response.json()["message"]["content"] == (
        "误分类恢复门店的本周营业额数据已取得。"
    )
    assert model.call_number == 5


async def test_business_question_fails_safely_when_analysis_keeps_skipping_tools(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    await user_factory(username="administrator", password="secret", role="admin")
    store = await store_factory(name="协议失败门店")
    await db_session.commit()
    await login(client, "administrator")
    model = RefusingBusinessToolModel()
    client._transport.app.state.agent_chat_graph = AgentChatGraph(model)

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "这周的营业额是多少？"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "AI 模型暂时不可用，请稍后重试"}
    assert model.call_number == 5
    restored = await client.get(f"/api/agent/stores/{store.id}/conversation")
    assert restored.json() == {"messages": []}


@pytest.mark.parametrize(
    "invalid_answer",
    [
        "不客气！如果还有其他需要，随时找我。",
        "星期一的经营日平均营业额为 120 元。",
    ],
)
async def test_store_data_answer_repairs_generic_closing_and_wrong_currency(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
    invalid_answer: str,
) -> None:
    await user_factory(username="administrator", password="secret", role="admin")
    store = await store_factory(name="回答恢复门店")
    await db_session.commit()
    await login(client, "administrator")

    async def new_read_tool(context, arguments):
        assert arguments == {}
        return {"weekday": "星期一", "average_revenue": 120}

    registry = AgentToolRegistry(
        [
            AgentTool(
                name="new_read_tool",
                description="读取星期经营数据。",
                parameters={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=new_read_tool,
            )
        ]
    )
    model = RecoveringAnswerModel(invalid_answer)
    client._transport.app.state.agent_chat_graph = AgentChatGraph(
        model, tool_registry=registry
    )

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "按星期分析这个月每天的营业额。"},
    )

    assert response.status_code == 200
    assert response.json()["message"]["content"] == (
        "星期一的经营日平均营业额为 120 欧元。"
    )
    assert model.call_number == 5


async def test_unexpected_tool_failure_is_safe_at_the_agent_http_seam(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    await user_factory(username="administrator", password="secret", role="admin")
    store = await store_factory(name="工具失败门店")
    await db_session.commit()
    await login(client, "administrator")

    async def failing_tool(context, arguments):
        raise RuntimeError("private SQL and endpoint detail")

    registry = AgentToolRegistry(
        [
            AgentTool(
                name="failing_tool",
                description="模拟失败的数据工具。",
                parameters={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=failing_tool,
            )
        ]
    )
    client._transport.app.state.agent_chat_graph = AgentChatGraph(
        FailingToolModel(), tool_registry=registry
    )

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "查看门店营业额"},
    )

    assert response.status_code == 200
    assert response.json()["message"]["content"] == (
        "暂时无法取得门店数据，请稍后重试。"
    )
    assert "private" not in response.text
    assert "SQL" not in response.text
