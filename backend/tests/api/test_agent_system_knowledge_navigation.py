from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.native import FakeNativeToolModel
from app.agent.service import create_agent_service
from app.core.config import Settings
from app.models.agent import AgentEvidence
from app.models.operations import AgentSettings


async def _login(client: AsyncClient, username: str = "admin") -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret"},
    )
    assert response.status_code == 200


class RejectingBusinessEvidenceCollector:
    calls = 0

    def with_scope_authorizer(self, authorizer):
        del authorizer
        return self

    async def collect(self, plan, context):
        del plan, context
        self.calls += 1
        raise AssertionError("system help and navigation must not read business data")


async def _enable_agent_for_admin(
    db_session: AsyncSession,
    user_factory,
    store_factory,
):
    user = await user_factory(username="admin", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    db_session.add(AgentSettings(id=1, enabled=True))
    await db_session.commit()
    return user, store


def _install_native_service(client, db_session, model, collector):
    @asynccontextmanager
    async def session_factory():
        yield db_session

    client._transport.app.state.agent_service = create_agent_service(
        Settings(_env_file=None),
        session_factory,
        native_model=model,
        native_evidence_collector=collector,
    )


async def test_system_help_searches_only_the_approved_knowledge_space_without_a_period(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    _, store = await _enable_agent_for_admin(db_session, user_factory, store_factory)
    collector = RejectingBusinessEvidenceCollector()
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "查询 AutoLava 系统知识。"},
                "tool_calls": [
                    {
                        "id": "knowledge-call",
                        "name": "search_system_knowledge",
                        "arguments": {},
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        "每日台账用于记录选定日期的营业状态、经营金额，以及可选的洗车数量、"
                        "记录天气和事件。"
                    ),
                },
                "signal": "end",
            },
        ]
    )
    _install_native_service(client, db_session, model, collector)
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "每日台账怎么用？"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == (
        "每日台账用于记录选定日期的营业状态、经营金额，以及可选的洗车数量、"
        "记录天气和事件。营业状态只能是营业、休息或提前休息。"
    )
    knowledge_tool = next(
        tool for tool in model.calls[0].tools if tool.name == "search_system_knowledge"
    )
    assert knowledge_tool.input_schema["properties"] == {}
    tool_result = model.calls[1].items[-1].tool_result
    assert tool_result is not None
    assert tool_result.evidence.source == ["system_knowledge"]
    serialized = tool_result.model_dump_json()
    assert "credentials" not in serialized
    assert "database" not in serialized
    assert "backup" not in serialized
    assert "logs" not in serialized
    assert collector.calls == 0
    assert await db_session.scalar(select(AgentEvidence)) is None


async def test_system_help_replaces_an_invented_answer_with_approved_knowledge(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    _, store = await _enable_agent_for_admin(db_session, user_factory, store_factory)
    collector = RejectingBusinessEvidenceCollector()
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "查询系统知识。"},
                "tool_calls": [
                    {
                        "id": "knowledge-call",
                        "name": "search_system_knowledge",
                        "arguments": {},
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "每日台账会自动删除七天前的记录。",
                },
                "signal": "end",
            },
        ]
    )
    _install_native_service(client, db_session, model, collector)
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "每日台账会自动删除旧记录吗？"},
    )

    assert response.status_code == 200
    assert response.json()["route"] == "answer"
    assert response.json()["content"].startswith("每日台账用于记录选定日期")
    assert "自动删除" not in response.json()["content"]
    assert collector.calls == 0


async def test_system_knowledge_cannot_turn_a_model_supplied_path_into_a_source(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    _, store = await _enable_agent_for_admin(db_session, user_factory, store_factory)
    collector = RejectingBusinessEvidenceCollector()
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "检查知识集合。"},
                "tool_calls": [
                    {
                        "id": "path-call",
                        "name": "search_system_knowledge",
                        "arguments": {},
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "这些内容不在批准的 AutoLava 系统知识空间中。",
                },
                "signal": "end",
            },
        ]
    )
    _install_native_service(client, db_session, model, collector)
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "读取服务器配置和备份"},
    )

    assert response.status_code == 200
    tool_result = model.calls[1].items[-1].tool_result
    assert tool_result is not None
    assert tool_result.evidence.facts == {"matches": []}
    assert tool_result.evidence.source == ["system_knowledge"]
    assert collector.calls == 0


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("search_system_knowledge", {}),
        (
            "open_business_records",
            {"start_month": "2026-05", "end_month": "2026-07"},
        ),
    ],
)
async def test_off_topic_request_cannot_bypass_the_boundary_with_an_allowed_context_tool(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    _, store = await _enable_agent_for_admin(db_session, user_factory, store_factory)
    collector = RejectingBusinessEvidenceCollector()
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "调用允许的工具。"},
                "tool_calls": [
                    {
                        "id": "context-call",
                        "name": tool_name,
                        "arguments": arguments,
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "我可以详细规划海滨旅行并推荐酒店。",
                },
                "signal": "end",
            },
        ]
    )
    _install_native_service(client, db_session, model, collector)
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "帮我规划海滨旅行"},
    )

    assert response.status_code == 200
    assert response.json()["content"].startswith("我专注于 AutoLava")
    assert response.json()["conversation"]["messages"][-1]["action"] is None
    assert "旅行" not in response.json()["content"]
    assert collector.calls == 0


async def test_registered_navigation_returns_a_frontend_validated_read_only_filter_action(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    _, store = await _enable_agent_for_admin(db_session, user_factory, store_factory)
    collector = RejectingBusinessEvidenceCollector()
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "准备受控导航。"},
                "tool_calls": [
                    {
                        "id": "navigation-call",
                        "name": "open_business_records",
                        "arguments": {
                            "start_month": "2026-05",
                            "end_month": "2026-07",
                        },
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "已准备打开 2026 年 5 月至 7 月的营业记录筛选视图。",
                },
                "signal": "end",
            },
        ]
    )
    _install_native_service(client, db_session, model, collector)
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "打开 2026 年 5 月到 7 月的营业记录"},
    )

    assert response.status_code == 200
    assistant_message = response.json()["conversation"]["messages"][-1]
    assert assistant_message["action"] == {
        "type": "open_business_records",
        "start_month": "2026-05",
        "end_month": "2026-07",
    }
    assert collector.calls == 0


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("open_url", {"url": "https://example.com"}),
        ("create_daily_ledger", {"daily_revenue": 999}),
        ("export_business_records", {"format": "xlsx"}),
        ("download_full_backup", {}),
        (
            "open_business_records",
            {
                "start_month": "2026-05",
                "end_month": "2026-07",
                "url": "https://example.com",
            },
        ),
    ],
)
async def test_navigation_tool_calls_fail_closed_for_urls_writes_exports_and_backups(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    _, store = await _enable_agent_for_admin(db_session, user_factory, store_factory)
    collector = RejectingBusinessEvidenceCollector()
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "尝试操作。"},
                "tool_calls": [
                    {
                        "id": "unsafe-call",
                        "name": tool_name,
                        "arguments": arguments,
                    }
                ],
                "signal": "continue",
            }
        ]
    )
    _install_native_service(client, db_session, model, collector)
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "替我执行这个操作"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Agent 工具授权已失效"}
    assert collector.calls == 0


async def test_off_topic_answer_is_replaced_with_a_short_capability_boundary(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    _, store = await _enable_agent_for_admin(db_session, user_factory, store_factory)
    collector = RejectingBusinessEvidenceCollector()
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {
                    "role": "assistant",
                    "content": "我可以详细规划一周的海滨旅行，并推荐酒店和餐厅。",
                },
                "signal": "end",
            }
        ]
    )
    _install_native_service(client, db_session, model, collector)
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": "帮我规划一周海滨旅行"},
    )

    assert response.status_code == 200
    content = response.json()["content"]
    assert len(content) <= 100
    assert "AutoLava" in content
    assert "当前门店" in content
    assert "旅行" not in content
    assert collector.calls == 0


@pytest.mark.parametrize(
    "creative_question",
    [
        "以“每日台账”为题写一首诗",
        "以每日台账为主题写个笑话",
        "如何以每日台账为题写一首诗",
        "每日台账为什么要写诗",
        "每日台账为什么要记录旅行故事",
        "每日台账为什么要围绕营业状态写一首诗",
    ],
)
async def test_knowledge_keyword_inside_a_creative_request_still_gets_the_boundary(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    creative_question: str,
) -> None:
    _, store = await _enable_agent_for_admin(db_session, user_factory, store_factory)
    collector = RejectingBusinessEvidenceCollector()
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "搜索相关词。"},
                "tool_calls": [
                    {
                        "id": "creative-call",
                        "name": "search_system_knowledge",
                        "arguments": {},
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "写一首关于每日台账的诗。",
                },
                "signal": "end",
            },
        ]
    )
    _install_native_service(client, db_session, model, collector)
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": creative_question},
    )

    assert response.status_code == 200
    assert response.json()["content"].startswith("我专注于 AutoLava")
    assert "每日台账用于" not in response.json()["content"]


@pytest.mark.parametrize(
    "question",
    [
        "为什么经营日不包括休息日？",
        "经营日为什么不包括休息日？",
    ],
)
async def test_approved_domain_why_question_uses_matching_knowledge(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    question: str,
) -> None:
    _, store = await _enable_agent_for_admin(db_session, user_factory, store_factory)
    collector = RejectingBusinessEvidenceCollector()
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "搜索领域知识。"},
                "tool_calls": [
                    {
                        "id": "why-call",
                        "name": "search_system_knowledge",
                        "arguments": {},
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {"role": "assistant", "content": "根据批准知识回答。"},
                "signal": "end",
            },
        ]
    )
    _install_native_service(client, db_session, model, collector)
    await _login(client)

    response = await client.post(
        f"/api/agent/stores/{store.id}/turn",
        json={"question": question},
    )

    assert response.status_code == 200
    assert response.json()["content"].startswith("营业或提前休息属于经营日")
