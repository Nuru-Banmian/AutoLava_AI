import pytest

from app.services.agent_calculation import (
    CalculationValidationError,
    calculate,
)
from app.services.agent_skills import (
    DataSkill,
    InvalidSkillCatalogError,
    SkillCatalog,
)


def test_skill_catalog_rejects_unknown_data_tool_at_startup() -> None:
    invalid = DataSkill(
        name="invalid",
        summary="无效 Skill",
        instructions="不得启动",
        allowed_data_tools=frozenset({"unknown_tool"}),
    )

    with pytest.raises(
        InvalidSkillCatalogError,
        match="unknown_tool",
    ):
        SkillCatalog(
            frozenset({"business_performance_summary"}),
            skills=(invalid,),
        )


def test_skill_catalog_rejects_registered_but_unauthorized_tool_at_startup() -> None:
    overreaching = DataSkill(
        name="business_performance",
        summary="越权 Skill",
        instructions="不得启动",
        allowed_data_tools=frozenset(
            {"business_performance_summary", "settlement_summary"}
        ),
    )

    with pytest.raises(
        InvalidSkillCatalogError,
        match="unauthorized.*settlement_summary",
    ):
        SkillCatalog(
            frozenset(
                {"business_performance_summary", "settlement_summary"}
            ),
            skills=(overreaching,),
        )


def test_calculation_rejects_cross_turn_result_reference() -> None:
    with pytest.raises(
        CalculationValidationError,
        match="本轮结果编号不存在",
    ):
        calculate(
            [
                {
                    "name": "difference",
                    "operation": "subtract",
                    "left": {
                        "result_id": "previous-turn-result",
                        "field": "data.ledger_revenue",
                    },
                    "right": {"literal": "10", "source": "user"},
                }
            ],
            results={},
        )


def test_calculation_requires_literal_source_and_reports_zero_divisor() -> None:
    with pytest.raises(
        CalculationValidationError,
        match="字面量必须标明来源",
    ):
        calculate(
            [
                {
                    "name": "invalid",
                    "operation": "add",
                    "left": {"literal": "1"},
                    "right": {"literal": "2", "source": "user"},
                }
            ],
            results={},
        )

    result = calculate(
        [
            {
                "name": "ratio",
                "operation": "divide",
                "left": {
                    "result_id": "result-1",
                    "field": "data.ledger_revenue",
                },
                "right": {"literal": "0", "source": "user"},
            }
        ],
        results={
            "result-1": {
                "data": {"ledger_revenue": "360"},
            }
        },
    )

    assert result == {
        "status": "completed",
        "values": {},
        "unavailable": {"ratio": "除数为零，无法计算"},
    }


@pytest.mark.parametrize(
    "operand",
    (
        {"literal": "NaN", "source": "user"},
        {
            "result_id": "result-1",
            "field": "data.non_finite",
        },
    ),
)
def test_calculation_rejects_non_finite_decimal(operand) -> None:
    with pytest.raises(
        CalculationValidationError,
        match="有限数值",
    ):
        calculate(
            [
                {
                    "name": "invalid",
                    "operation": "add",
                    "left": operand,
                    "right": {"literal": "1", "source": "user"},
                }
            ],
            results={
                "result-1": {"data": {"non_finite": "Infinity"}},
            },
        )


def test_calculation_propagates_expected_unavailable_operands() -> None:
    result = calculate(
        [
            {
                "name": "missing_average",
                "operation": "add",
                "left": {
                    "result_id": "result-1",
                    "field": "data.average_revenue_per_wash",
                },
                "right": {"literal": "1", "source": "user"},
            },
            {
                "name": "zero_ratio",
                "operation": "divide",
                "left": {
                    "result_id": "result-1",
                    "field": "data.ledger_revenue",
                },
                "right": {"literal": "0", "source": "user"},
            },
            {
                "name": "uses_unavailable_step",
                "operation": "add",
                "left": {"step": "zero_ratio"},
                "right": {"literal": "1", "source": "user"},
            },
        ],
        results={
            "result-1": {
                "data": {
                    "ledger_revenue": "360",
                    "average_revenue_per_wash": None,
                }
            }
        },
    )

    assert result == {
        "status": "completed",
        "values": {},
        "unavailable": {
            "missing_average": "引用值不可用",
            "zero_ratio": "除数为零，无法计算",
            "uses_unavailable_step": "除数为零，无法计算",
        },
    }
