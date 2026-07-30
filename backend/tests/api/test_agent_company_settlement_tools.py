from collections.abc import Sequence
from datetime import date, datetime
import json

from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentSystemSettings
from app.models.ledger import StoreDailyRecord
from app.models.settlement import SettlementCompany, SettlementRecord
from app.services.agent_model import ModelResponse, ModelToolCall


class CompanySettlementAdapter:
    def __init__(self) -> None:
        self.step = 0
        self.last_messages: Sequence[dict[str, object]] = ()
        self.tools: Sequence[dict[str, object]] = ()

    async def respond(self, messages, tools) -> ModelResponse:
        self.step += 1
        self.last_messages = messages
        self.tools = tools
        if self.step == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="load-settlement",
                        name="load_skill",
                        arguments={"name": "company_settlement"},
                    ),
                )
            )
        if self.step == 2:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="summary-month",
                        name="company_settlement_summary",
                        arguments={
                            "start_month": "2026-06",
                            "end_month": "2026-07",
                            "group_by": "opening_month",
                        },
                    ),
                    ModelToolCall(
                        id="summary-company",
                        name="company_settlement_summary",
                        arguments={
                            "start_month": "2026-06",
                            "end_month": "2026-07",
                            "group_by": "company",
                        },
                    ),
                )
            )
        if self.step == 3:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="detail",
                        name="company_settlement_detail",
                        arguments={
                            "start_month": "2026-06",
                            "end_month": "2026-07",
                            "company_id": 1,
                            "statuses": ["pending"],
                            "limit": 1,
                            "offset": 0,
                        },
                    ),
                    ModelToolCall(
                        id="directory",
                        name="settlement_company_directory",
                        arguments={
                            "statuses": ["active", "archived"],
                            "limit": 50,
                            "offset": 0,
                        },
                    ),
                )
            )
        return ModelResponse(
            content=(
                "2026 年 6–7 月已确认公司结算收入为 300 欧元；"
                "当前待到账应收款为 200 欧元，不计入营业额。"
                "这些应收款仅表示当前状态，不是过去日期的历史快照；"
                "公司结算按开票月份归属，没有到账日期或日粒度。"
            )
        )


class UnsafeSettlementAnswerAdapter:
    def __init__(self, content: str) -> None:
        self.step = 0
        self.content = content

    async def respond(self, _messages, _tools) -> ModelResponse:
        self.step += 1
        if self.step == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="load-settlement",
                        name="load_skill",
                        arguments={"name": "company_settlement"},
                    ),
                )
            )
        if self.step == 2:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="summary",
                        name="company_settlement_summary",
                        arguments={
                            "start_month": "2026-07",
                            "end_month": "2026-07",
                            "group_by": "opening_month",
                        },
                    ),
                )
            )
        return ModelResponse(content=self.content)


class UnsafeSettlementCalculationAdapter:
    def __init__(self) -> None:
        self.step = 0

    async def respond(self, _messages, _tools) -> ModelResponse:
        self.step += 1
        if self.step == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="load-settlement",
                        name="load_skill",
                        arguments={"name": "company_settlement"},
                    ),
                )
            )
        if self.step == 2:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="summary",
                        name="company_settlement_summary",
                        arguments={
                            "start_month": "2026-07",
                            "end_month": "2026-07",
                            "group_by": "opening_month",
                        },
                    ),
                )
            )
        return ModelResponse(
            tool_calls=(
                ModelToolCall(
                    id="unsafe-total",
                    name="calculate",
                    arguments={
                        "steps": [
                            {
                                "name": "wrong_total",
                                "operation": "add",
                                "left": {
                                    "result_id": "result-1",
                                    "field": (
                                        "data.confirmed_settlement_income"
                                    ),
                                },
                                "right": {
                                    "literal": "100",
                                    "source": "同期开票已确认公司结算收入",
                                },
                            }
                        ]
                    },
                ),
            )
        )


class SafePartialMonthTotalAdapter:
    def __init__(
        self,
        *,
        reuse_total_as_operating_days: bool = False,
    ) -> None:
        self.step = 0
        self.reuse_total_as_operating_days = (
            reuse_total_as_operating_days
        )

    async def respond(self, _messages, _tools) -> ModelResponse:
        self.step += 1
        if self.step == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="load-settlement",
                        name="load_skill",
                        arguments={"name": "company_settlement"},
                    ),
                )
            )
        if self.step == 2:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="settlement-summary",
                        name="company_settlement_summary",
                        arguments={
                            "start_month": "2026-07",
                            "end_month": "2026-07",
                            "group_by": "opening_month",
                        },
                    ),
                    ModelToolCall(
                        id="performance-summary",
                        name="business_performance_summary",
                        arguments={
                            "start": "2026-07-15",
                            "end": "2026-07-29",
                        },
                    ),
                )
            )
        if self.step == 3:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="receivables-comparison",
                        name="calculate",
                        arguments={
                            "steps": [
                                {
                                    "name": "pending_minus_confirmed",
                                    "operation": "subtract",
                                    "left": {
                                        "result_id": "result-1",
                                        "field": (
                                            "data.current_pending_receivables"
                                        ),
                                    },
                                    "right": {
                                        "result_id": "result-1",
                                        "field": (
                                            "data.confirmed_settlement_income"
                                        ),
                                    },
                                },
                                {
                                    "name": "monthly_total",
                                    "operation": "add",
                                    "left": {
                                        "result_id": "result-2",
                                        "field": "data.ledger_revenue",
                                    },
                                    "right": {
                                        "result_id": "result-1",
                                        "field": (
                                            "data.confirmed_settlement_income"
                                        ),
                                    },
                                },
                            ]
                        },
                    ),
                )
            )
        return ModelResponse(
            content=(
                "所选期间台账营业额为 400 欧元，已确认公司结算收入为 "
                "100 欧元，当前待到账应收款为 150 欧元，不计入营业额。"
                "两者相差 50 欧元。"
                "月度总收入合计约为 500 欧元。"
                + (
                    "经营日为 500 天。"
                    if self.reuse_total_as_operating_days
                    else ""
                )
            )
        )


class StreamingSettlementAdapter:
    def __init__(
        self,
        *,
        unsafe_total: bool = False,
        combined_unsafe_suffix: bool = False,
    ) -> None:
        self.step = 0
        self.unsafe_total = unsafe_total
        self.combined_unsafe_suffix = combined_unsafe_suffix

    async def respond(self, _messages, _tools) -> ModelResponse:
        raise AssertionError("tool-enabled streaming response must be used")

    async def respond_stream(self, _messages, _tools):
        self.step += 1
        if self.step == 1:
            yield ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="load-settlement",
                        name="load_skill",
                        arguments={"name": "company_settlement"},
                    ),
                )
            )
            return
        if self.step == 2:
            yield ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="settlement-summary",
                        name="company_settlement_summary",
                        arguments={
                            "start_month": "2026-07",
                            "end_month": "2026-07",
                            "group_by": "opening_month",
                        },
                    ),
                )
            )
            return
        if self.combined_unsafe_suffix:
            yield ModelResponse(
                content=(
                    "已确认公司结算收入为 100 欧元。"
                    "两项合计收入为 250 欧元"
                )
            )
            return
        yield ModelResponse(content="已确认公司结算收入为 100 欧元。")
        yield ModelResponse(content="当前待到账应收款为 150 欧元，")
        yield ModelResponse(
            content=(
                "不计入营业额。两项合计收入为 250 欧元。"
                if self.unsafe_total
                else "不计入营业额。"
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


async def _seed_guard_case(
    db_session: AsyncSession,
    user_factory,
    store_factory,
    *,
    username: str,
) -> tuple[object, int]:
    admin = await user_factory(
        username=username,
        password="secret123",
        role="admin",
    )
    store = await store_factory(name=f"{username} 门店")
    company = SettlementCompany(
        store_id=store.id,
        name="Guard Company",
        normalized_name="guard company",
        is_active=True,
        archived_at=None,
        created_by=admin.id,
        updated_by=admin.id,
    )
    db_session.add_all((AgentSystemSettings(enabled=True), company))
    await db_session.flush()
    db_session.add_all(
        (
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 20),
                daily_revenue=400,
                is_open="营业",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=100,
                status="confirmed",
                revision=2,
                created_by=admin.id,
                updated_by=admin.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=150,
                status="pending",
                revision=1,
                created_by=admin.id,
                updated_by=admin.id,
            ),
        )
    )
    store_id = store.id
    await db_session.commit()
    return admin, store_id


async def test_agent_analyzes_settlement_income_and_current_receivables_separately(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="settlement-agent-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="公司结算分析门店")
    store.company_settlement_enabled = False
    alpha = SettlementCompany(
        store_id=store.id,
        name="Alpha",
        normalized_name="alpha",
        is_active=True,
        archived_at=None,
        created_by=admin.id,
        updated_by=admin.id,
    )
    beta = SettlementCompany(
        store_id=store.id,
        name="Beta",
        normalized_name="beta",
        is_active=False,
        archived_at=datetime(2026, 7, 5),
        created_by=admin.id,
        updated_by=admin.id,
    )
    no_history = SettlementCompany(
        store_id=store.id,
        name="No History",
        normalized_name="no history",
        is_active=True,
        archived_at=None,
        created_by=admin.id,
        updated_by=admin.id,
    )
    db_session.add_all(
        (AgentSystemSettings(enabled=True), alpha, beta, no_history)
    )
    await db_session.flush()
    db_session.add_all(
        (
            SettlementRecord(
                store_id=store.id,
                company_id=alpha.id,
                company_name=alpha.name,
                opening_month=date(2026, 6, 1),
                amount=100,
                status="confirmed",
                revision=2,
                created_by=admin.id,
                updated_by=admin.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=alpha.id,
                company_name=alpha.name,
                opening_month=date(2026, 6, 1),
                amount=50,
                status="pending",
                revision=1,
                created_by=admin.id,
                updated_by=admin.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=alpha.id,
                company_name=alpha.name,
                opening_month=date(2026, 7, 1),
                amount=150,
                status="pending",
                revision=1,
                created_by=admin.id,
                updated_by=admin.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=beta.id,
                company_name=beta.name,
                opening_month=date(2026, 7, 1),
                amount=200,
                status="confirmed",
                revision=2,
                created_by=admin.id,
                updated_by=admin.id,
            ),
        )
    )
    store_id = store.id
    alpha_id = alpha.id
    beta_id = beta.id
    no_history_id = no_history.id
    await db_session.commit()
    adapter = CompanySettlementAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={
            "content": (
                "分析 2026 年 6 月到 7 月公司结算收入、当前待到账应收款和月度总收入"
            )
        },
    )

    assert response.status_code == 200
    assert '"type":"failed"' not in response.text, response.text
    payloads = _tool_payloads(adapter.last_messages)
    skill = next(payload for payload in payloads if "instructions" in payload)
    month_summary, company_summary = [
        payload
        for payload in payloads
        if payload.get("data", {}).get("group_by")
        in {"opening_month", "company"}
    ]
    detail = next(
        payload
        for payload in payloads
        if "records" in payload.get("data", {})
    )
    directory = next(
        payload
        for payload in payloads
        if "companies" in payload.get("data", {})
    )

    assert month_summary["data"] == {
        "group_by": "opening_month",
        "confirmed_settlement_income": "300",
        "current_pending_receivables": "200",
        "groups": [
            {
                "opening_month": "2026-06",
                "confirmed_settlement_income": "100",
                "current_pending_receivables": "50",
            },
            {
                "opening_month": "2026-07",
                "confirmed_settlement_income": "200",
                "current_pending_receivables": "150",
            },
        ],
    }
    assert company_summary["data"]["groups"] == [
        {
            "company_id": alpha_id,
            "company_name": "Alpha",
            "confirmed_settlement_income": "100",
            "current_pending_receivables": "200",
        },
        {
            "company_id": beta_id,
            "company_name": "Beta",
            "confirmed_settlement_income": "200",
            "current_pending_receivables": "0",
        },
    ]
    assert detail["data"]["records"] == [
        {
            "record_id": detail["data"]["records"][0]["record_id"],
            "opening_month": "2026-06",
            "company_id": alpha_id,
            "company_name": "Alpha",
            "amount": "50",
            "status": "pending",
        }
    ]
    assert detail["coverage"] == {
        "range_start": "2026-06-01",
        "range_end": "2026-07-31",
        "matching_records": 2,
        "returned_records": 1,
        "truncated": True,
        "next_offset": 1,
        "state_basis": "current",
    }
    assert directory["data"]["companies"] == [
        {
            "company_id": alpha_id,
            "company_name": "Alpha",
            "status": "active",
        },
        {
            "company_id": no_history_id,
            "company_name": "No History",
            "status": "active",
        },
        {
            "company_id": beta_id,
            "company_name": "Beta",
            "status": "archived",
        },
    ]
    assert directory["coverage"]["matching_companies"] == 3
    assert directory["coverage"]["includes_companies_without_records"] is True
    assert directory["coverage"]["company_settlement_enabled"] is False
    assert set(skill["allowed_data_tools"]) == {
        "company_settlement_detail",
        "company_settlement_summary",
        "settlement_company_directory",
        "business_performance_summary",
    }
    for requirement in (
        "待到账应收款不计入营业额",
        "当前状态",
        "不是历史快照",
        "不按到账日期",
        "不得分配到日粒度",
        "功能关闭",
    ):
        assert requirement in skill["instructions"]
    tool_names = {
        tool["function"]["name"] for tool in adapter.tools
    }
    assert {
        "company_settlement_summary",
        "company_settlement_detail",
        "settlement_company_directory",
    } <= tool_names
    assert "当前待到账应收款为 200 欧元，不计入营业额" in response.text
    assert "不是过去日期的历史快照" in response.text


@pytest.mark.parametrize(
    "unsafe_answer",
    (
        (
            "已确认公司结算收入为 100 欧元；当前待到账应收款为 150 欧元，"
            "不计入营业额。两项合计收入为 250 欧元。"
        ),
        (
            "**已确认公司结算收入**为 100 欧元；当前待到账应收款为 "
            "150 欧元，不计入营业额。**月度总收入**合计约为 250 欧元。"
        ),
        (
            "2026 年 7 月 1 日已确认公司结算收入为 100 欧元；"
            "当前待到账应收款为 150 欧元，不计入营业额。"
        ),
        (
            "已确认公司结算收入与当前待到账应收款分开说明。"
            "7/1 的已确认结算收入为 100 欧元；"
            "当前待到账应收款为 150 欧元，不计入营业额。"
        ),
    ),
)
async def test_agent_rejects_unsafe_settlement_final_answer(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    unsafe_answer: str,
) -> None:
    admin, store_id = await _seed_guard_case(
        db_session,
        user_factory,
        store_factory,
        username="unsafe-answer-admin",
    )
    client._transport.app.state.agent_model_adapter = (
        UnsafeSettlementAnswerAdapter(unsafe_answer)
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026 年 7 月公司结算和待到账应收款"},
    )

    events = [
        json.loads(line) for line in response.text.splitlines() if line
    ]
    assert any(event["type"] == "failed" for event in events)
    assert all(event["type"] != "answer_delta" for event in events)


async def test_agent_allows_partial_month_ledger_plus_confirmed_settlement_total(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin, store_id = await _seed_guard_case(
        db_session,
        user_factory,
        store_factory,
        username="safe-partial-total-admin",
    )
    client._transport.app.state.agent_model_adapter = (
        SafePartialMonthTotalAdapter()
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026 年 7 月 15 日到 29 日月度总收入"},
    )

    events = [
        json.loads(line) for line in response.text.splitlines() if line
    ]
    assert any(event["type"] == "completed" for event in events)
    assert all(event["type"] != "failed" for event in events)
    assert "月度总收入合计约为 500 欧元" in response.text


async def test_settlement_total_cannot_be_reused_as_an_unrelated_metric(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin, store_id = await _seed_guard_case(
        db_session,
        user_factory,
        store_factory,
        username="settlement-total-metric-collision-admin",
    )
    client._transport.app.state.agent_model_adapter = (
        SafePartialMonthTotalAdapter(reuse_total_as_operating_days=True)
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026 年 7 月 15 日到 29 日月度总收入"},
    )

    events = [
        json.loads(line) for line in response.text.splitlines() if line
    ]
    assert all(event["type"] != "answer_delta" for event in events)
    assert events[-1]["type"] == "failed"

    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation",
    )
    assert all(
        message["role"] != "assistant"
        for message in restored.json()["messages"]
    )


async def test_agent_rejects_calculation_that_combines_pending_and_revenue(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin, store_id = await _seed_guard_case(
        db_session,
        user_factory,
        store_factory,
        username="unsafe-calculation-admin",
    )
    client._transport.app.state.agent_model_adapter = (
        UnsafeSettlementCalculationAdapter()
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026 年 7 月公司结算和待到账应收款"},
    )

    events = [
        json.loads(line) for line in response.text.splitlines() if line
    ]
    assert any(event["type"] == "failed" for event in events)
    assert all(event["type"] != "answer_delta" for event in events)


async def test_company_settlement_answer_streams_safe_sentence_fragments(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin, store_id = await _seed_guard_case(
        db_session,
        user_factory,
        store_factory,
        username="streaming-settlement-admin",
    )
    client._transport.app.state.agent_model_adapter = (
        StreamingSettlementAdapter()
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026 年 7 月公司结算和待到账应收款"},
    )

    events = [
        json.loads(line) for line in response.text.splitlines() if line
    ]
    assert [
        event["delta"] for event in events if event["type"] == "answer_delta"
    ] == [
        "已确认公司结算收入为 100 欧元。",
        "当前待到账应收款为 150 欧元，不计入营业额。",
    ]
    assert events[-1]["type"] == "completed"


async def test_company_settlement_stream_withholds_an_unsafe_later_fragment(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin, store_id = await _seed_guard_case(
        db_session,
        user_factory,
        store_factory,
        username="unsafe-streaming-settlement-admin",
    )
    client._transport.app.state.agent_model_adapter = (
        StreamingSettlementAdapter(unsafe_total=True)
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026 年 7 月公司结算和待到账应收款"},
    )

    events = [
        json.loads(line) for line in response.text.splitlines() if line
    ]
    assert [
        event["delta"] for event in events if event["type"] == "answer_delta"
    ] == ["已确认公司结算收入为 100 欧元。"]
    assert "250" not in response.text
    assert events[-1]["type"] == "failed"


async def test_company_settlement_stream_releases_only_safe_prefix_of_one_chunk(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin, store_id = await _seed_guard_case(
        db_session,
        user_factory,
        store_factory,
        username="unsafe-single-chunk-settlement-admin",
    )
    client._transport.app.state.agent_model_adapter = (
        StreamingSettlementAdapter(combined_unsafe_suffix=True)
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026 年 7 月公司结算和待到账应收款"},
    )

    events = [
        json.loads(line) for line in response.text.splitlines() if line
    ]
    assert [
        event["delta"] for event in events if event["type"] == "answer_delta"
    ] == ["已确认公司结算收入为 100 欧元。"]
    assert "250" not in response.text
    assert events[-1]["type"] == "failed"
