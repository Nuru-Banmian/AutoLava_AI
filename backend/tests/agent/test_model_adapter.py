import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from app.agent.contracts import ModelMessage, TurnPlan
from app.agent.model import (
    FakeModelAdapter,
    ModelAdapterError,
    OpenAICompatibleModelAdapter,
    OpenAICompatibleProfile,
    RepairableModelPlanError,
    UnsafeModelPlanError,
)


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

    with pytest.raises(RepairableModelPlanError, match="invalid structured model output"):
        await adapter.plan_turn([])
    with pytest.raises(ModelAdapterError, match="provider secret"):
        await adapter.plan_turn([])


async def test_production_adapter_does_not_repair_raw_output_with_store_scope() -> None:
    class StructuredClient:
        def with_structured_output(self, _schema, **options):
            assert options["include_raw"] is True
            return self

        async def ainvoke(self, _messages):
            return {
                "raw": AIMessage(
                    content=(
                        '{"route":"evidence","evidence_plan":{"requests":['
                        '{"kind":"business_metrics",'
                        '"metric":"monthly_total_revenue","store_id":999}]}}'
                    )
                ),
                "parsed": None,
                "parsing_error": ValueError("extra field"),
            }

    adapter = OpenAICompatibleModelAdapter(
        OpenAICompatibleProfile(
            base_url="https://model.example/v1",
            model_id="test-model",
            api_key=SecretStr("secret"),
        ),
        client=StructuredClient(),
    )

    with pytest.raises(UnsafeModelPlanError):
        await adapter.plan_turn([])
