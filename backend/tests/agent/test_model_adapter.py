import pytest

from app.agent.contracts import ModelMessage, TurnPlan
from app.agent.model import FakeModelAdapter, ModelAdapterError


async def test_fake_model_adapter_returns_scripted_plans_without_network() -> None:
    adapter = FakeModelAdapter(
        plans=[
            {"route": "clarify", "question": "请提供准确日期。"},
            {"route": "direct_answer", "answer": "这是直接回答。"},
        ]
    )
    messages = [ModelMessage(role="user", content="帮我看看")]

    first = await adapter.plan_turn(messages)
    second = await adapter.plan_turn(messages)

    assert first == TurnPlan(route="clarify", question="请提供准确日期。")
    assert second == TurnPlan(route="direct_answer", answer="这是直接回答。")
    assert adapter.plan_calls == 2


async def test_fake_model_adapter_surfaces_invalid_structure_and_model_failure() -> None:
    adapter = FakeModelAdapter(
        plans=[
            {"route": "not-a-route"},
            ModelAdapterError("provider secret must never be returned"),
        ]
    )

    with pytest.raises(ModelAdapterError, match="invalid structured model output"):
        await adapter.plan_turn([])
    with pytest.raises(ModelAdapterError, match="provider secret"):
        await adapter.plan_turn([])
