import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime

from httpx import AsyncClient

from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.settlement import SettlementCompany, SettlementRecord
from app.services.agent_chat import AgentChatGraph


class ToolFlowModel:
    def __init__(
        self,
        *,
        understanding: str,
        arguments: dict[str, str],
        answer: str,
        call_id: str,
    ) -> None:
        self.understanding = understanding
        self.arguments = arguments
        self.answer = answer
        self.call_id = call_id
        self.call_number = 0
        self.tool_result: dict[str, object] | None = None
        self.tools: Sequence[Mapping[str, object]] | None = None

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        tools: Sequence[Mapping[str, object]] | None = None,
    ) -> Mapping[str, object]:
        self.call_number += 1
        if self.call_number == 1:
            return {"content": self.understanding}
        if self.call_number == 2:
            assert tools is not None
            self.tools = tools
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": self.call_id,
                        "type": "function",
                        "function": {
                            "name": "get_period_revenue",
                            "arguments": json.dumps(
                                self.arguments,
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }

        tool_message = next(message for message in messages if message["role"] == "tool")
        self.tool_result = json.loads(str(tool_message["content"]))
        return {"content": self.answer}


async def login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret"},
    )
    assert response.status_code == 200


async def test_period_revenue_is_composed_and_store_scoped_through_http(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    administrator = await user_factory(
        username="period-admin", password="secret", role="admin"
    )
    store = await store_factory(name="期间收入门店", timezone="Europe/Rome")
    store.income_items_enabled = True
    store.company_settlement_enabled = True
    other_store = await store_factory(name="其他门店", timezone="Europe/Rome")
    other_store.company_settlement_enabled = True
    included = IncomeCategory(
        store_id=store.id,
        name="现金",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    excluded = IncomeCategory(
        store_id=store.id,
        name="其他数据",
        include_in_total=False,
        is_active=True,
        sort_order=1,
    )
    db_session.add_all([included, excluded])
    await db_session.flush()
    daily_record = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 15),
        daily_revenue=100,
        income_mode="composed",
        is_open="营业",
        created_by=administrator.id,
        updated_by=administrator.id,
    )
    db_session.add(daily_record)
    await db_session.flush()
    db_session.add_all(
        [
            DailyIncomeItem(
                record_id=daily_record.id,
                category_id=included.id,
                category_name=included.name,
                include_in_total=True,
                sort_order=0,
                amount=100,
            ),
            DailyIncomeItem(
                record_id=daily_record.id,
                category_id=excluded.id,
                category_name=excluded.name,
                include_in_total=False,
                sort_order=1,
                amount=900,
            ),
        ]
    )
    company = SettlementCompany(
        store_id=store.id,
        name="车队甲",
        normalized_name="车队甲",
        created_by=administrator.id,
        updated_by=administrator.id,
    )
    other_company = SettlementCompany(
        store_id=other_store.id,
        name="其他车队",
        normalized_name="其他车队",
        created_by=administrator.id,
        updated_by=administrator.id,
    )
    db_session.add_all([company, other_company])
    await db_session.flush()
    company_id = company.id
    db_session.add_all(
        [
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=40,
                status="confirmed",
                created_by=administrator.id,
                updated_by=administrator.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 6, 1),
                amount=300,
                status="pending",
                created_by=administrator.id,
                updated_by=administrator.id,
            ),
            SettlementRecord(
                store_id=other_store.id,
                company_id=other_company.id,
                company_name=other_company.name,
                opening_month=date(2026, 7, 1),
                amount=9999,
                status="confirmed",
                created_by=administrator.id,
                updated_by=administrator.id,
            ),
        ]
    )
    await db_session.commit()
    await login(client, administrator.username)
    answer = (
        "2026 年 7 月月度台账营业额为 100 欧元，已确认公司结算收入为 "
        "40 欧元，月度总收入为 140 欧元。当前待到账应收款 300 欧元，"
        "未计入上述收入。"
    )
    model = ToolFlowModel(
        understanding="用户询问上个月的期间收入。",
        arguments={"period": "上个月", "settlement_group_by": "company"},
        answer=answer,
        call_id="period-revenue-call",
    )
    app = client._transport.app
    app.state.agent_clock = lambda: datetime(2026, 7, 31, 22, 30, tzinfo=UTC)
    app.state.agent_chat_graph = AgentChatGraph(model)

    response = await client.post(
        f"/api/agent/stores/{store.id}/messages",
        json={"content": "上个月营业额和公司结算是多少？"},
    )

    assert response.status_code == 200
    assert model.call_number == 4
    assert model.tools is not None
    period_tool = next(
        tool
        for tool in model.tools
        if tool["function"]["name"] == "get_period_revenue"
    )
    assert period_tool["function"]["parameters"]["required"] == ["period"]
    assert model.tool_result == {
        "status": "success",
        "period": {
            "input": "上个月",
            "start": "2026-07-01",
            "end": "2026-07-31",
            "timezone": "Europe/Rome",
        },
        "daily_ledger_revenue": 100,
        "confirmed_settlement_income": 40,
        "total_income": 140,
        "monthly": [
            {
                "month": "2026-07",
                "daily_ledger_revenue": 100,
                "confirmed_settlement_income": 40,
                "monthly_total_income": 140,
            }
        ],
        "current_pending_receivables": 300,
        "settlement_breakdown": [
            {
                "company_id": company_id,
                "company_name": "车队甲",
                "confirmed_settlement_income": 40,
                "current_pending_receivables": 300,
            }
        ],
    }
    assert "9999" not in json.dumps(model.tool_result, ensure_ascii=False)
    assert response.json()["message"]["content"].endswith("未计入上述收入。")


async def test_relative_and_explicit_periods_return_normal_empty_results_through_http(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    administrator = await user_factory(
        username="empty-period-admin", password="secret", role="admin"
    )
    store = await store_factory(name="空期间门店", timezone="Europe/Rome")
    store_id = store.id
    await db_session.commit()
    await login(client, administrator.username)
    app = client._transport.app
    app.state.agent_clock = lambda: datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    cases = [
        ("这周", "2026-08-10", "2026-08-13"),
        ("本周", "2026-08-10", "2026-08-13"),
        ("这个月", "2026-08-01", "2026-08-13"),
        ("本月", "2026-08-01", "2026-08-13"),
        ("今年", "2026-01-01", "2026-08-13"),
        ("最近三周", "2026-07-24", "2026-08-13"),
        ("2026年7月1日至31日", "2026-07-01", "2026-07-31"),
    ]

    for period, expected_start, expected_end in cases:
        model = ToolFlowModel(
            understanding=f"已识别查询期间：{period}。",
            arguments={"period": period},
            answer="这个期间暂无匹配的营业额或公司结算数据。",
            call_id="empty-period-call",
        )
        app.state.agent_chat_graph = AgentChatGraph(model)
        response = await client.post(
            f"/api/agent/stores/{store_id}/messages",
            json={"content": f"查询{period}的营业额"},
        )

        assert response.status_code == 200
        assert model.tool_result is not None
        assert model.tool_result["status"] == "empty"
        assert model.tool_result["period"] == {
            "input": period,
            "start": expected_start,
            "end": expected_end,
            "timezone": "Europe/Rome",
        }
        assert response.json()["message"]["content"] == (
            "这个期间暂无匹配的营业额或公司结算数据。"
        )


async def test_settlement_breakdown_uses_current_company_identity_and_supported_groups(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    administrator = await user_factory(
        username="settlement-breakdown-admin", password="secret", role="admin"
    )
    store = await store_factory(name="结算构成门店", timezone="Europe/Rome")
    store_id = store.id
    company = SettlementCompany(
        store_id=store_id,
        name="车队新名",
        normalized_name="车队新名",
        created_by=administrator.id,
        updated_by=administrator.id,
    )
    db_session.add(company)
    await db_session.flush()
    company_id = company.id
    db_session.add_all(
        [
            SettlementRecord(
                store_id=store_id,
                company_id=company_id,
                company_name="车队旧名",
                opening_month=date(2026, 7, 1),
                amount=80,
                status="confirmed",
                created_by=administrator.id,
                updated_by=administrator.id,
            ),
            SettlementRecord(
                store_id=store_id,
                company_id=company_id,
                company_name="车队旧名",
                opening_month=date(2026, 6, 1),
                amount=20,
                status="pending",
                created_by=administrator.id,
                updated_by=administrator.id,
            ),
        ]
    )
    await db_session.commit()
    await login(client, administrator.username)
    app = client._transport.app
    app.state.agent_clock = lambda: datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    expected = {
        "company": [
            {
                "company_id": company_id,
                "company_name": "车队新名",
                "confirmed_settlement_income": 80,
                "current_pending_receivables": 20,
            }
        ],
        "opening_month": [
            {
                "opening_month": "2026-06",
                "confirmed_settlement_income": 0,
                "current_pending_receivables": 20,
            },
            {
                "opening_month": "2026-07",
                "confirmed_settlement_income": 80,
                "current_pending_receivables": 0,
            },
        ],
        "status": [
            {
                "status": "confirmed",
                "confirmed_settlement_income": 80,
                "current_pending_receivables": 0,
            },
            {
                "status": "pending",
                "confirmed_settlement_income": 0,
                "current_pending_receivables": 20,
            },
        ],
    }

    for group_by, expected_rows in expected.items():
        model = ToolFlowModel(
            understanding=f"用户要求按 {group_by} 查看结算构成。",
            arguments={"period": "上个月", "settlement_group_by": group_by},
            answer="已按要求整理公司结算与当前待到账应收款构成。",
            call_id=f"settlement-{group_by}",
        )
        app.state.agent_chat_graph = AgentChatGraph(model)
        response = await client.post(
            f"/api/agent/stores/{store_id}/messages",
            json={"content": f"按 {group_by} 查看上个月公司结算构成"},
        )

        assert response.status_code == 200
        assert model.tool_result is not None
        assert model.tool_result["settlement_breakdown"] == expected_rows


async def test_invalid_periods_fail_safely_at_the_agent_http_seam(
    client: AsyncClient,
    db_session,
    user_factory,
    store_factory,
) -> None:
    administrator = await user_factory(
        username="invalid-period-admin", password="secret", role="admin"
    )
    store = await store_factory(name="期间校验门店", timezone="Europe/Rome")
    store_id = store.id
    await db_session.commit()
    await login(client, administrator.username)
    app = client._transport.app
    app.state.agent_clock = lambda: datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    cases = [
        ("2026-08-14 至 2026-08-20", "期间结束日期不能晚于门店当地今天"),
        ("2026-08-10 至 2026-08-01", "期间起始日期不能晚于结束日期"),
        (
            "前阵子",
            "无法识别期间，请使用这周、本月、上个月、今年、最近若干周或明确起止日期",
        ),
    ]

    for period, expected_error in cases:
        model = ToolFlowModel(
            understanding="需要由后端校验用户要求的期间。",
            arguments={"period": period},
            answer=f"无法查询：{expected_error}。请确认期间后重试。",
            call_id="invalid-period",
        )
        app.state.agent_chat_graph = AgentChatGraph(model)
        response = await client.post(
            f"/api/agent/stores/{store_id}/messages",
            json={"content": f"查询{period}的营业额"},
        )

        assert response.status_code == 200
        assert model.tool_result == {"status": "error", "error": expected_error}
        assert response.json()["message"]["content"] == (
            f"无法查询：{expected_error}。请确认期间后重试。"
        )
