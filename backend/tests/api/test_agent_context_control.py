from collections.abc import Sequence
from datetime import date
import json

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConversation, AgentSystemSettings
from app.services.agent_conversation import (
    capability_gap_terms,
    interpret_time_scope,
)
from app.services.agent_model import ModelResponse, ModelToolCall
from app.services.agent_turn import _submitted_capability_answer


class ContextRecordingAdapter:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[dict[str, str]],
    ) -> str:
        self.calls.append([dict(message) for message in messages])
        return f"已回答第 {len(self.calls)} 轮经营问题。"


class MissingCapabilityAdapter:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    async def respond(self, messages, _tools) -> ModelResponse:
        self.calls.append([dict(message) for message in messages])
        if len(self.calls) == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="external-search",
                        name="web_search",
                        arguments={"query": "附近竞品价格" * 2_000},
                    ),
                )
            )
        return ModelResponse(
            content=(
                "当前门店本月营业额可以继续通过已有数据工具调查。"
                "无法访问附近竞品价格。当地通常收费 35 欧元。"
            )
        )


async def _login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200


def test_capability_answer_handles_empty_evidence() -> None:
    answer = _submitted_capability_answer(
        {"evidence": []},
        results={},
        missing_capabilities=("未来天气",),
    )

    assert "未来天气" in answer
    assert "本轮尚未形成带本轮结果编号的可信结论" in answer
    assert "不会声称已经取得这些数据" in answer


def test_supported_ledger_language_is_not_a_capability_gap() -> None:
    assert capability_gap_terms("分析本月台账营业额") == ()


def test_explicit_quarter_is_normalized_without_clarification() -> None:
    decision = interpret_time_scope(
        "分析 2026年第一季度的台账营业额",
        local_date=date(2026, 7, 30),
    )

    assert decision.direct_answer is None
    assert decision.guidance == (
        "已解析时间范围：2026-01-01 至 2026-03-31。"
        "数据工具必须使用该范围，不要自行扩大、缩小或替换。",
    )


def test_capability_answer_renders_settlement_boundary_in_domain_language() -> None:
    answer = _submitted_capability_answer(
        {
            "evidence": [
                {
                    "result_id": "result-1",
                    "fields": [
                        "data.confirmed_settlement_income",
                    ],
                }
            ]
        },
        results={
            "result-1": {
                "data": {
                    "confirmed_settlement_income": "100",
                    "current_pending_receivables": "50",
                }
            }
        },
        missing_capabilities=("外部公司信用数据",),
    )

    assert "已确认公司结算收入为 100欧元" in answer
    assert "当前待到账应收款为 50欧元" in answer
    assert "当前待到账应收款不计入营业额或月度总收入" in answer


def test_capability_answer_renders_trend_rows_without_raw_json() -> None:
    answer = _submitted_capability_answer(
        {
            "evidence": [
                {
                    "result_id": "result-1",
                    "fields": ["data.points"],
                },
                {
                    "result_id": "result-2",
                    "fields": ["data.companies"],
                }
            ]
        },
        results={
            "result-1": {
                "data": {
                    "points": [
                        {
                            "period": "2026-07-01",
                            "ledger_revenue": "120",
                        }
                    ]
                }
            },
            "result-2": {
                "data": {
                    "companies": [
                        {
                            "company_name": "示例公司",
                            "status": "archived",
                        }
                    ]
                }
            },
        },
        missing_capabilities=("未来天气",),
    )

    assert "台账营业额趋势" in answer
    assert "期间为 2026-07-01" in answer
    assert "台账营业额为 120欧元" in answer
    assert "结算公司为 示例公司" in answer
    assert "状态为 已归档" in answer
    assert "archived" not in answer
    assert '"ledger_revenue"' not in answer


async def test_model_context_is_bounded_while_full_conversation_remains_visible(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="bounded-context-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="上下文门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    admin_id = admin.id
    adapter = ContextRecordingAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    questions = [
        f"分析经营情况 {10_000 + index}"
        for index in range(1, 7)
    ]
    for question in questions:
        response = await client.post(
            f"/api/agent/stores/{store_id}/messages",
            json={"content": question},
        )
        assert response.status_code == 200

    restored = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()
    assert len(restored["messages"]) == 12
    assert restored["messages"][0]["content"] == questions[0]

    last_context = adapter.calls[-1]
    assert sum(len(message["content"]) for message in last_context) <= 12_000
    assert not any(
        message["role"] == "user"
        and message["content"] == questions[0]
        for message in last_context
    )
    summary = next(
        message["content"]
        for message in last_context
        if message["role"] == "system"
        and message["content"].startswith("精简会话摘要：")
    )
    assert "10001" in summary
    assert last_context[-1] == {
        "role": "user",
        "content": questions[-1],
    }

    conversation = await db_session.scalar(
        select(AgentConversation).where(
            AgentConversation.user_id == admin.id,
            AgentConversation.store_id == store_id,
        )
    )
    assert conversation is not None
    await db_session.refresh(conversation)
    assert "10001" in conversation.context_summary

    reset = await client.delete(
        f"/api/agent/stores/{store_id}/conversation"
    )
    assert reset.status_code == 204
    assert (
        await db_session.scalar(
            select(AgentConversation).where(
                AgentConversation.user_id == admin_id,
                AgentConversation.store_id == store_id,
            )
        )
        is None
    )


async def test_explicit_time_range_is_normalized_without_clarification(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="explicit-range-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="明确期间门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    adapter = ContextRecordingAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "分析 2026-07-01 至 2026-07-31 的营业额"},
    )

    assert response.status_code == 200
    assert len(adapter.calls) == 1
    assert any(
        message["role"] == "system"
        and "已解析时间范围：2026-07-01 至 2026-07-31" in message["content"]
        for message in adapter.calls[0]
    )


async def test_explicit_single_day_is_normalized_without_clarification(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="explicit-day-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="明确单日门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    adapter = ContextRecordingAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    for question in (
        "分析 2026-07-15 的营业额",
        "分析 2026年7月15日 的营业额",
    ):
        response = await client.post(
            f"/api/agent/stores/{store_id}/messages",
            json={"content": question},
        )
        assert response.status_code == 200

    assert len(adapter.calls) == 2
    for messages in adapter.calls:
        assert any(
            message["role"] == "system"
            and "已解析时间范围：2026-07-15 至 2026-07-15"
            in message["content"]
            for message in messages
        )


async def test_ambiguous_spoken_period_asks_for_the_missing_boundary(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="ambiguous-range-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="含糊期间门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    adapter = ContextRecordingAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析最近的营业额"},
    )

    assert response.status_code == 200
    assert adapter.calls == []
    conversation = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()
    answer = conversation["messages"][-1]["content"]
    assert "“最近”无法唯一确定时间范围" in answer
    assert "最近 30 天" in answer


async def test_incomparable_explicit_ranges_are_not_silently_rewritten(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="incomparable-range-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="比较期间门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    adapter = ContextRecordingAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={
            "content": (
                "比较 2026-07-01 至 2026-07-07 与 "
                "2026-06-01 至 2026-06-30 的营业额"
            )
        },
    )

    assert response.status_code == 200
    assert adapter.calls == []
    conversation = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()
    answer = conversation["messages"][-1]["content"]
    assert "两个期间长度不同，不能直接比较" in answer
    assert "相同天数" in answer
    assert "没有替你修改原始范围" in answer


async def test_incomparable_quantified_ranges_are_both_parsed(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="quantified-range-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="量化期间门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    adapter = ContextRecordingAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "比较最近 7 天和过去 30 天的营业额"},
    )

    assert response.status_code == 200
    assert adapter.calls == []
    conversation = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()
    answer = conversation["messages"][-1]["content"]
    assert "两个期间长度不同，不能直接比较" in answer
    assert "相同天数" in answer


async def test_capability_gap_keeps_partial_answer_and_rejects_unavailable_claim(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="capability-gap-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="能力边界门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    adapter = MissingCapabilityAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={
            "content": (
                "分析本月营业额，并结合附近竞品价格给出能确认的部分"
            )
        },
    )

    assert response.status_code == 200
    assert len(adapter.calls) == 2
    assert all(
        len(
            json.dumps(
                messages,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        <= 12_000
        for messages in adapter.calls
    )
    unavailable_result = next(
        message["content"]
        for message in adapter.calls[-1]
        if message["role"] == "tool"
    )
    assert '"status":"unavailable"' in unavailable_result
    conversation = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()
    answer = conversation["messages"][-1]["content"]
    assert "本轮尚未形成带本轮结果编号的可信结论" in answer
    assert "附近竞品价格为 35 欧元" not in answer
    assert "当地通常收费 35 欧元" not in answer
    assert "无法访问附近竞品价格" in answer

    follow_up = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析本月营业额"},
    )
    assert follow_up.status_code == 200
    assert all(
        message["role"] != "tool"
        for message in adapter.calls[-1]
    )


async def test_mixed_business_and_news_question_keeps_the_answerable_part(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="mixed-news-gap-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="新闻能力边界门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id

    class MixedNewsAdapter(ContextRecordingAdapter):
        async def complete(
            self,
            messages: Sequence[dict[str, str]],
        ) -> str:
            self.calls.append([dict(message) for message in messages])
            return "当前门店本月营业额仍可由数据工具调查。"

    adapter = MixedNewsAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析本月营业额，并结合外部新闻解释变化"},
    )

    assert response.status_code == 200
    assert adapter.calls == []
    conversation = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()
    answer = conversation["messages"][-1]["content"]
    assert "本轮尚未形成带本轮结果编号的可信结论" in answer
    assert "无法访问外部新闻" in answer
    assert "只能帮助你分析 Agent 当前门店" not in answer


async def test_capability_boundary_preserves_numeric_business_evidence(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="numeric-partial-answer-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="数值部分回答门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id

    class NumericPartialAnswerAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def respond(self, messages, _tools) -> ModelResponse:
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    tool_calls=(
                        ModelToolCall(
                            id="load-performance",
                            name="load_skill",
                            arguments={"name": "business_performance"},
                        ),
                    )
                )
            if self.calls == 2:
                return ModelResponse(
                    tool_calls=(
                        ModelToolCall(
                            id="performance-summary",
                            name="business_performance_summary",
                                arguments={
                                    "start": "2026-07-01",
                                    "end": "2026-07-29",
                            },
                        ),
                    )
                )
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="submit-supported-answer",
                        name="submit_answer",
                        arguments={
                            "evidence": [
                                {
                                    "result_id": "result-1",
                                    "fields": ["data.ledger_revenue"],
                                }
                            ]
                        },
                    ),
                )
            )

    adapter = NumericPartialAnswerAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析7月营业额，并结合附近竞品价格解释变化"},
    )

    assert response.status_code == 200
    conversation = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()
    answer = conversation["messages"][-1]["content"]
    assert adapter.calls == 3
    assert "根据本轮结果编号 result-1" in answer
    assert "台账营业额为" in answer
    assert "data.ledger_revenue" not in answer
    assert "无法访问附近竞品价格" in answer


async def test_invalid_capability_answer_citation_falls_back_safely(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="invalid-gap-citation-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="无效引用门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id

    class InvalidCitationAdapter:
        async def respond(self, _messages, _tools) -> ModelResponse:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="submit-forged-answer",
                        name="submit_answer",
                        arguments={
                            "evidence": [
                                {
                                    "result_id": "result-999",
                                    "fields": ["data.ledger_revenue"],
                                }
                            ]
                        },
                    ),
                )
            )

    client._transport.app.state.agent_model_adapter = InvalidCitationAdapter()
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析本月营业额，并结合竞争对手数据"},
    )

    assert response.status_code == 200
    conversation = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()
    answer = conversation["messages"][-1]["content"]
    assert "5000 欧元" not in answer
    assert "本轮尚未形成带本轮结果编号的可信结论" in answer
    assert "无法访问竞争对手数据" in answer


async def test_unlisted_capability_gap_still_returns_a_bounded_partial_answer(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="generic-gap-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="通用能力边界门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id

    class ExchangeRateGapAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def respond(self, _messages, _tools) -> ModelResponse:
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    tool_calls=(
                        ModelToolCall(
                            id="exchange-rate",
                            name="exchange_rate_lookup",
                            arguments={"currency": "EUR"},
                        ),
                    )
                )
            return ModelResponse(
                content=(
                    "当前门店营业额仍可调查。"
                    "虽然无法访问欧元汇率，但换算标准约 1.2。"
                )
            )

    adapter = ExchangeRateGapAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析本月营业额，并用欧元汇率修正"},
    )

    assert response.status_code == 200
    assert adapter.calls == 2
    conversation = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()
    answer = conversation["messages"][-1]["content"]
    assert "本轮尚未形成带本轮结果编号的可信结论" in answer
    assert "换算标准约 1.2" not in answer
    assert "无法访问欧元汇率" in answer

    for question in (
        "本月营业额和欧元汇率有什么关系",
        "把本月营业额按当前欧元汇率换算",
    ):
        follow_up = await client.post(
            f"/api/agent/stores/{store_id}/messages",
            json={"content": question},
        )
        assert follow_up.status_code == 200
    conversation = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()
    follow_up_answers = [
        message["content"]
        for message in conversation["messages"][-4:]
        if message["role"] == "assistant"
    ]
    assert len(follow_up_answers) == 2
    assert all(
        "本轮尚未形成带本轮结果编号的可信结论" in answer
        and "能力边界" in answer
        and "汇率" in answer
        for answer in follow_up_answers
    )


async def test_mixed_period_forms_are_compared_together(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="mixed-period-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="混合期间门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    adapter = ContextRecordingAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    for question in (
        "比较最近 7 天和上个月的营业额",
        "比较 2026-07-01 至 2026-07-07 与上个月的营业额",
    ):
        response = await client.post(
            f"/api/agent/stores/{store_id}/messages",
            json={"content": question},
        )
        assert response.status_code == 200

    assert adapter.calls == []
    conversation = (
        await client.get(f"/api/agent/stores/{store_id}/conversation")
    ).json()
    answers = [
        message["content"]
        for message in conversation["messages"]
        if message["role"] == "assistant"
    ]
    assert len(answers) == 2
    assert all(
        "两个期间长度不同，不能直接比较" in answer
        and "没有替你修改原始范围" in answer
        for answer in answers
    )


async def test_chinese_and_abbreviated_explicit_periods_do_not_prompt(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="localized-period-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="本地期间门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    adapter = ContextRecordingAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    for question in (
        "分析最近两周的营业额",
        "分析 2026年7月1日至31日 的营业额",
        "分析 2026年7月 的营业额",
    ):
        response = await client.post(
            f"/api/agent/stores/{store_id}/messages",
            json={"content": question},
        )
        assert response.status_code == 200

    assert len(adapter.calls) == 3
    assert any(
        message["role"] == "system"
        and "已解析时间范围：" in message["content"]
        for message in adapter.calls[0]
    )
    for messages in adapter.calls[1:]:
        assert any(
            message["role"] == "system"
            and "已解析时间范围：2026-07-01 至 2026-07-31"
            in message["content"]
            for message in messages
        )
