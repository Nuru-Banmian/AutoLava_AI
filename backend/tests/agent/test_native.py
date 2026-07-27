from datetime import datetime, timezone

from app.agent.conversation import ConversationState
from app.agent.contracts import ModelMessage
from app.agent.native import FakeNativeToolModel, NativeToolAgentService
from app.agent.runtime import RuntimeContext, RuntimeFeatureFlags


class FailingEvidenceCollector:
    calls = 0

    async def collect(self, plan, context):
        del plan, context
        self.calls += 1
        raise RuntimeError("database details must not reach the model")


async def test_native_tool_failure_is_returned_to_the_model_in_the_unified_envelope() -> None:
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "查询。"},
                "tool_calls": [
                    {
                        "id": "failed-call",
                        "name": "monthly_total_revenue",
                        "arguments": {"year": 2026, "month": 7},
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "经营查询暂时不可用，目前无法确认月度总收入。",
                },
                "signal": "end",
            },
        ]
    )
    service = NativeToolAgentService(
        model=model,
        evidence_collector=FailingEvidenceCollector(),
        now=lambda: datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc),
    )

    result = await service.run(
        RuntimeContext(
            user_id=1,
            store_id=2,
            role="admin",
            store_timezone="Europe/Rome",
            features=RuntimeFeatureFlags(
                agent_enabled=True,
                company_settlement_enabled=True,
                income_items_enabled=True,
                wash_count_enabled=True,
            ),
        ),
        ConversationState(),
        [ModelMessage(role="user", content="2026 年 7 月收入是多少？")],
    )

    tool_result = model.calls[1].items[-1].tool_result
    assert tool_result is not None
    assert tool_result.evidence.failure.model_dump() == {
        "status": "failed",
        "category": "business_query_unavailable",
        "message": "经营查询暂时不可用",
    }
    assert tool_result.evidence.facts == {}
    assert tool_result.evidence.scope.id == 2
    assert "database details" not in tool_result.model_dump_json()
    assert result.evidence is None
    assert result.turn.content == "经营查询暂时不可用，目前无法确认月度总收入。"


async def test_native_loop_does_not_let_the_model_guess_an_unconfirmed_month() -> None:
    collector = FailingEvidenceCollector()
    model = FakeNativeToolModel(turns=[])
    service = NativeToolAgentService(model=model, evidence_collector=collector)

    result = await service.run(
        RuntimeContext(
            user_id=1,
            store_id=2,
            role="admin",
            store_timezone="Europe/Rome",
            features=RuntimeFeatureFlags(
                agent_enabled=True,
                company_settlement_enabled=True,
                income_items_enabled=True,
                wash_count_enabled=True,
            ),
        ),
        ConversationState(),
        [ModelMessage(role="user", content="最近的月度总收入是多少？")],
    )

    assert result.turn.route == "clarify"
    assert result.turn.content == "请提供要查询的准确自然月，例如“2026 年 7 月”。"
    assert model.calls == []
    assert collector.calls == 0
