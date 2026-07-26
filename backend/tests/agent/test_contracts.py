import pytest
from pydantic import ValidationError

from app.agent.contracts import EvidencePlan, EvidenceRequest, TurnPlan


@pytest.mark.parametrize(
    "plan",
    (
        {"route": "clarify", "question": "请说明要查询的准确日期。"},
        {"route": "direct_answer", "answer": "我可以帮助查询当前门店的经营数据。"},
        {
            "route": "evidence",
            "evidence_plan": {
                "requests": [
                    {"kind": "business_metrics"}
                ]
            },
        },
        {"route": "safe_failure", "message": "当前无法安全处理该问题。"},
    ),
)
def test_turn_plan_accepts_each_closed_route(plan: dict[str, object]) -> None:
    assert TurnPlan.model_validate(plan).route == plan["route"]


@pytest.mark.parametrize(
    "plan",
    (
        {"route": "unknown", "message": "continue"},
        {"route": "clarify", "question": "哪一天？", "sql": "select * from users"},
        {"route": "direct_answer", "question": "wrong field"},
        {"route": "evidence", "evidence_plan": {"requests": []}},
        {
            "route": "evidence",
            "evidence_plan": {
                "requests": [
                    {
                        "kind": "business_metrics",
                        "question": "select * from users",
                    }
                ]
            },
        },
    ),
)
def test_turn_plan_rejects_unknown_fields_illegal_routes_and_wrong_shapes(
    plan: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TurnPlan.model_validate(plan)


def test_evidence_plan_has_a_bounded_request_count() -> None:
    request = EvidenceRequest(kind="business_metrics")

    with pytest.raises(ValidationError):
        EvidencePlan(requests=[request] * 5)
