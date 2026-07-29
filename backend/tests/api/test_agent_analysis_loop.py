from collections.abc import Sequence
from datetime import date
import json

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentSystemSettings
from app.models.ledger import StoreDailyRecord
from app.services.agent_model import ModelResponse, ModelToolCall


class AnalysisModelAdapter:
    def __init__(self) -> None:
        self.calls: list[Sequence[dict[str, object]]] = []
        self.step = 0

    async def respond(
        self,
        messages: Sequence[dict[str, object]],
        tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        self.calls.append(messages)
        self.step += 1
        if self.step == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="load-performance",
                        name="load_skill",
                        arguments={"name": "business_performance"},
                    ),
                )
            )
        if self.step == 2:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="performance-summary",
                        name="business_performance_summary",
                        arguments={
                            "start": "2026-07-01",
                            "end": "2026-07-03",
                        },
                    ),
                )
            )
        if self.step == 3:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="target-difference",
                        name="calculate",
                        arguments={
                            "steps": [
                                {
                                    "name": "above_target",
                                    "operation": "subtract",
                                    "left": {
                                        "result_id": "result-1",
                                        "field": "data.ledger_revenue",
                                    },
                                    "right": {
                                        "literal": "100",
                                        "source": "user",
                                    },
                                }
                            ]
                        },
                    ),
                )
            )
        return ModelResponse(
            content=(
                "7 月 1 日至 3 日台账营业额为 360 欧元，2 个经营日，"
                "经营日均台账营业额为 180 欧元；比你给出的 100 欧元目标高 260 欧元。"
                "洗车数量只覆盖其中 1 个经营日，平均每车收入为 60 欧元。"
            )
        )


async def _login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200


def _events(response_text: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in response_text.splitlines() if line]


async def test_http_turn_loads_skill_queries_data_calculates_and_persists_cards(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="analysis-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="分析门店")
    db_session.add_all(
        (
            AgentSystemSettings(enabled=True),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 1),
                daily_revenue=240,
                wash_count=4,
                is_open="营业",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 2),
                daily_revenue=120,
                wash_count=None,
                is_open="提前休息",
                created_by=admin.id,
                updated_by=admin.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 3),
                daily_revenue=0,
                wash_count=None,
                is_open="休息",
                created_by=admin.id,
                updated_by=admin.id,
            ),
        )
    )
    await db_session.commit()
    store_id = store.id
    adapter = AnalysisModelAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={
            "content": (
                "分析 2026-07-01 到 2026-07-03 的经营表现，"
                "并告诉我比 100 欧元目标高多少"
            )
        },
    )

    assert response.status_code == 200
    events = _events(response.text)
    cards = [
        event["card"]
        for event in events
        if event["type"] == "investigation_card"
    ]
    assert cards == [
        {
            "operation": "汇总经营表现",
            "range_start": "2026-07-01",
            "range_end": "2026-07-03",
            "filters": [],
            "status": "completed",
        },
        {
            "operation": "完成派生计算",
            "range_start": None,
            "range_end": None,
            "filters": [],
            "status": "completed",
        },
    ]
    assert all(
        forbidden not in json.dumps(cards, ensure_ascii=False)
        for forbidden in ("360", "result-1", "daily_revenue", "arguments")
    )
    assert events[-1]["type"] == "completed"

    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation",
    )
    payload = restored.json()
    assert payload["latest_turn"]["status"] == "completed"
    assert payload["messages"][-1]["content"].startswith(
        "7 月 1 日至 3 日台账营业额为 360 欧元"
    )
    assert payload["latest_turn"]["investigation_cards"] == cards

    tool_results = [
        json.loads(message["content"])
        for message in adapter.calls[-1]
        if message["role"] == "tool"
    ]
    summary = next(item for item in tool_results if "result_id" in item)
    calculation = next(item for item in tool_results if "values" in item)
    assert summary["data"] == {
        "ledger_revenue": "360",
        "operating_days": 2,
        "operating_day_average_ledger_revenue": "180",
        "wash_count": "4",
        "average_revenue_per_wash": "60",
    }
    assert summary["coverage"]["missing_wash_count_days"] == 1
    assert calculation["values"]["above_target"] == "260"


async def test_business_performance_empty_range_is_a_successful_empty_result(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="empty-analysis-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="空数据门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id

    class EmptyRangeAdapter:
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
                            id="load",
                            name="load_skill",
                            arguments={"name": "business_performance"},
                        ),
                    )
                )
            if self.step == 2:
                return ModelResponse(
                    tool_calls=(
                        ModelToolCall(
                            id="summary",
                            name="business_performance_summary",
                            arguments={
                                "start": "2026-07-01",
                                "end": "2026-07-03",
                            },
                        ),
                    )
                )
            return ModelResponse(content="该期间没有匹配的每日台账数据。")

    adapter = EmptyRangeAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026-07-01 到 2026-07-03 的经营表现"},
    )

    assert response.status_code == 200
    assert _events(response.text)[-1]["type"] == "completed"
    summary = next(
        json.loads(message["content"])
        for message in adapter.last_messages
        if message["role"] == "tool"
        and "result_id" in json.loads(message["content"])
    )
    assert summary["status"] == "empty"
    assert summary["coverage"]["matching_records"] == 0
    assert summary["coverage"]["operating_days"] == 0
