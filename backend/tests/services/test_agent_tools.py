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
