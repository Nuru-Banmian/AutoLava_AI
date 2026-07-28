from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, cast

from pydantic import Field, StringConstraints, model_validator

from app.agent.contracts import ClosedModel


EvidenceReference = Annotated[
    str,
    StringConstraints(pattern=r"^ev_[0-9a-f]{24}$"),
]
CalculationUnit = Literal[
    "EUR",
    "day",
    "car",
    "EUR/car",
    "EUR/operating_day",
    "ratio",
    "percent",
]
CannotCalculateReason = Literal[
    "reference_not_current",
    "stale_reference",
    "unauthorized_reference",
    "input_unavailable",
    "incompatible_units",
    "zero_denominator",
]
MAX_REFERENCE_AGE = timedelta(minutes=15)


class EvidenceCalculationRequest(ClosedModel):
    operation: Literal["sum", "difference", "ratio", "percentage_change"] = Field(
        description=("固定运算。percentage_change 按第一个引用为基准、第二个引用为当前值计算。")
    )
    evidence_references: list[EvidenceReference] = Field(
        min_length=2,
        max_length=8,
        description="仅可使用本轮工具已经返回的证据引用；除 sum 外必须正好两个。",
    )

    @model_validator(mode="after")
    def require_distinct_references(self) -> EvidenceCalculationRequest:
        if len(set(self.evidence_references)) != len(self.evidence_references):
            raise ValueError("calculation evidence references must be distinct")
        if self.operation != "sum" and len(self.evidence_references) != 2:
            raise ValueError(f"{self.operation} requires exactly two evidence references")
        return self


class EvidenceCalculationResult(ClosedModel):
    formula: str | None
    input_evidence_references: list[EvidenceReference]
    exact_result: Decimal | None
    unit: CalculationUnit | None
    cannot_calculate_reason: CannotCalculateReason | None


class EvidenceCalculationInput(ClosedModel):
    reference: EvidenceReference
    primary_value: Decimal | None
    unit: Literal["EUR", "day", "car", "EUR/car", "EUR/operating_day"] | None
    store_id: int = Field(gt=0)
    queried_at: datetime
    data_version: str = Field(min_length=1, max_length=100)
    available: bool


def calculate_evidence(
    request: EvidenceCalculationRequest,
    available_evidence: Mapping[EvidenceReference, EvidenceCalculationInput],
    *,
    current_store_id: int,
    now: datetime,
) -> EvidenceCalculationResult:
    operands: list[Decimal] = []
    units: list[str] = []
    for reference in request.evidence_references:
        available = available_evidence.get(reference)
        if available is None:
            return _failure(request, "reference_not_current")
        if available.store_id != current_store_id:
            return _failure(request, "unauthorized_reference")
        age = now - available.queried_at
        if age < timedelta(0) or age > MAX_REFERENCE_AGE:
            return _failure(request, "stale_reference")
        if not available.available or available.primary_value is None or available.unit is None:
            return _failure(request, "input_unavailable")
        operands.append(available.primary_value)
        units.append(available.unit)
    if any(unit != units[0] for unit in units[1:]):
        return _failure(request, "incompatible_units")
    references = request.evidence_references
    if request.operation == "sum":
        formula = " + ".join(references)
        exact_result = sum(operands, start=Decimal(0))
        unit = units[0]
    elif request.operation == "difference":
        formula = f"{references[0]} - {references[1]}"
        exact_result = operands[0] - operands[1]
        unit = units[0]
    elif request.operation == "ratio":
        if operands[1] == 0:
            return _failure(request, "zero_denominator")
        formula = f"{references[0]} / {references[1]}"
        exact_result = operands[0] / operands[1]
        unit = "ratio"
    else:
        if operands[0] == 0:
            return _failure(request, "zero_denominator")
        formula = f"({references[1]} - {references[0]}) / {references[0]} * 100"
        exact_result = (operands[1] - operands[0]) / operands[0] * 100
        unit = "percent"
    return EvidenceCalculationResult(
        formula=formula,
        input_evidence_references=references,
        exact_result=exact_result,
        unit=cast(CalculationUnit, unit),
        cannot_calculate_reason=None,
    )


def _failure(
    request: EvidenceCalculationRequest,
    reason: CannotCalculateReason,
) -> EvidenceCalculationResult:
    return EvidenceCalculationResult(
        formula=None,
        input_evidence_references=request.evidence_references,
        exact_result=None,
        unit=None,
        cannot_calculate_reason=reason,
    )
