from typing import Any

from app.agent.contracts import EvidenceBundle, ModelMessage
from app.agent.model import FakeModelAdapter, ModelAdapterError
from app.agent.workflow import AgentTurnWorkflow


class RecordingEvidenceCollector:
    def __init__(self) -> None:
        self.calls = 0

    async def collect(self, plan: Any) -> EvidenceBundle:
        self.calls += 1
        return EvidenceBundle(summary="本月月度总收入为 100 欧元。")


async def test_workflow_finishes_clarification_without_collecting_evidence() -> None:
    model = FakeModelAdapter(plans=[{"route": "clarify", "question": "请说明准确日期。"}])
    collector = RecordingEvidenceCollector()

    result = await AgentTurnWorkflow(model=model, evidence_collector=collector).run(
        [ModelMessage(role="user", content="最近收入如何？")]
    )

    assert result.route == "clarify"
    assert result.content == "请说明准确日期。"
    assert collector.calls == 0
    assert model.total_calls == 1


async def test_workflow_collects_once_then_generates_one_complete_answer() -> None:
    model = FakeModelAdapter(
        plans=[
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {"kind": "business_metrics"}
                    ]
                },
            }
        ],
        answers=["本月月度总收入为 100 欧元。"],
    )
    collector = RecordingEvidenceCollector()

    result = await AgentTurnWorkflow(model=model, evidence_collector=collector).run(
        [ModelMessage(role="user", content="本月收入是多少？")]
    )

    assert result.route == "answer"
    assert result.content == "本月月度总收入为 100 欧元。"
    assert collector.calls == 1
    assert model.plan_calls == 1
    assert model.answer_calls == 1
    assert model.total_calls == 2


async def test_workflow_converts_model_failure_to_a_sanitized_safe_failure() -> None:
    model = FakeModelAdapter(plans=[ModelAdapterError("api-key=real-secret")])

    result = await AgentTurnWorkflow(
        model=model,
        evidence_collector=RecordingEvidenceCollector(),
    ).run([ModelMessage(role="user", content="本月收入是多少？")])

    assert result.route == "safe_failure"
    assert result.content == "模型服务暂时不可用，请稍后重试。"
    assert "real-secret" not in result.content
