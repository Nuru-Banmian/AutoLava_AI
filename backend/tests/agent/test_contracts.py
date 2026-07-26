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
                    {
                        "kind": "business_metrics",
                        "metric": "monthly_total_revenue",
                    }
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
                        "metric": "monthly_total_revenue",
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
    request = EvidenceRequest(
        kind="business_metrics",
        metric="monthly_total_revenue",
    )

    with pytest.raises(ValidationError):
        EvidencePlan(requests=[request] * 2)


def test_evidence_request_has_at_most_one_bounded_group_position() -> None:
    request = EvidenceRequest(
        kind="business_metrics",
        metric="income_category_amount",
        group_by="income_category",
    )

    assert request.group_by == "income_category"
    with pytest.raises(ValidationError):
        EvidencePlan.model_validate(
            {
                "requests": [
                    {
                        "kind": "business_metrics",
                        "metric": "income_category_amount",
                        "group_by": ["income_category", "date"],
                    }
                ]
            }
        )
    with pytest.raises(ValidationError):
        EvidenceRequest(
            kind="business_metrics",
            metric="daily_ledger_revenue",
            group_by="income_category",
        )


def test_evidence_metric_whitelist_fails_closed() -> None:
    with pytest.raises(ValidationError):
        EvidenceRequest(
            kind="business_metrics",
            metric="arbitrary_sql_metric",
        )


@pytest.mark.parametrize(
    "untrusted_field",
    (
        "sql",
        "table",
        "field",
        "expression",
        "url",
        "store_id",
        "user_id",
        "role",
        "timezone",
    ),
)
def test_evidence_plan_rejects_model_owned_scope_and_query_fields(
    untrusted_field: str,
) -> None:
    request = {
        "kind": "business_metrics",
        "metric": "monthly_total_revenue",
        untrusted_field: "untrusted",
    }

    with pytest.raises(ValidationError):
        EvidencePlan.model_validate({"requests": [request]})
