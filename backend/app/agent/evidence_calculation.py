from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


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


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceCalculationRequest(ClosedModel):
    operation: Literal["sum", "difference", "ratio", "percentage_change"]
    evidence_references: list[EvidenceReference] = Field(min_length=2, max_length=8)

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


class EvidenceValueEnvelope(Protocol):
    @property
    def facts(self) -> dict[str, Any]: ...

    @property
    def unit(self) -> str: ...

    @property
    def scope(self) -> Any: ...

    @property
    def queried_at(self) -> datetime: ...

    @property
    def failure(self) -> Any: ...


_PRIMARY_FACT_BY_TOOL = {
    "monthly_total_revenue": "monthly_total_revenue",
    "daily_ledger_revenue": "daily_ledger_revenue",
    "confirmed_settlement_income": "confirmed_settlement_income",
    "operating_days": "operating_days",
    "operating_day_average_ledger_revenue": "operating_day_average_ledger_revenue",
    "monthly_daily_average_income": "monthly_daily_average_income",
    "wash_count": "wash_count",
    "average_revenue_per_car": "average_revenue_per_car",
    "income_category_amount": "amount",
    "other_data_amount": "amount",
    "daily_ledger_revenue_extreme": "daily_ledger_revenue",
}
_INPUT_UNITS: frozenset[str] = frozenset({"EUR", "day", "car", "EUR/car", "EUR/operating_day"})


def calculate_evidence(
    request: EvidenceCalculationRequest,
    available_evidence: Mapping[
        EvidenceReference,
        tuple[str, EvidenceValueEnvelope],
    ],
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
        tool_name, envelope = available
        if envelope.scope.id != current_store_id:
            return _failure(request, "unauthorized_reference")
        age = now - envelope.queried_at
        if age < timedelta(0) or age > MAX_REFERENCE_AGE:
            return _failure(request, "stale_reference")
        if envelope.failure.status != "none":
            return _failure(request, "input_unavailable")
        fact_name = _PRIMARY_FACT_BY_TOOL.get(tool_name)
        value = envelope.facts.get(fact_name) if fact_name is not None else None
        if (
            value is None
            or isinstance(value, bool)
            or not isinstance(value, (int, float, Decimal))
            or envelope.unit not in _INPUT_UNITS
        ):
            return _failure(request, "input_unavailable")
        operands.append(Decimal(str(value)))
        units.append(envelope.unit)
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
