from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.agent.evidence_calculation import (
    EvidenceCalculationRequest,
    calculate_evidence,
)
from app.agent.native import (
    NativeEvidenceEnvelope,
    NativeEvidenceFailure,
)
from app.agent.contracts import (
    CurrentStoreScope,
    EvidenceCoverage,
    EvidencePeriodResult,
)


NOW = datetime(2026, 7, 28, 10, 1, tzinfo=timezone.utc)


def _evidence(
    reference: str,
    value: int | None,
    *,
    unit: str = "EUR",
    store_id: int = 2,
    queried_at: datetime = datetime(2026, 7, 28, 10, tzinfo=timezone.utc),
    failed: bool = False,
) -> NativeEvidenceEnvelope:
    return NativeEvidenceEnvelope(
        reference=reference,
        facts={} if value is None else {"monthly_total_revenue": value},
        scope=CurrentStoreScope(id=store_id),
        period=EvidencePeriodResult(start=date(2026, 7, 1), end=date(2026, 7, 31)),
        unit=unit,
        source=["store_daily_records"],
        queried_at=queried_at,
        data_version=f"sha256:{reference}",
        coverage=EvidenceCoverage(calendar_dates=31, recorded_dates=31),
        truncated=False,
        failure=NativeEvidenceFailure(
            status="failed" if failed else "none",
            category="business_query_unavailable" if failed else None,
            message="经营查询暂时不可用" if failed else None,
        ),
    )


def test_calculation_uses_only_declared_current_evidence_references() -> None:
    first = _evidence("ev_111111111111111111111111", 140)
    second = _evidence("ev_222222222222222222222222", 100)

    result = calculate_evidence(
        EvidenceCalculationRequest(
            operation="difference",
            evidence_references=[first.reference, second.reference],
        ),
        {
            first.reference: ("monthly_total_revenue", first),
            second.reference: ("monthly_total_revenue", second),
        },
        current_store_id=2,
        now=NOW,
    )

    assert result.formula == f"{first.reference} - {second.reference}"
    assert result.input_evidence_references == [first.reference, second.reference]
    assert result.exact_result == Decimal("40")
    assert result.unit == "EUR"
    assert result.cannot_calculate_reason is None


@pytest.mark.parametrize(
    ("operation", "values", "expected", "unit", "formula"),
    [
        ("sum", (100, 40), Decimal("140"), "EUR", "{first} + {second}"),
        ("difference", (140, 100), Decimal("40"), "EUR", "{first} - {second}"),
        ("ratio", (140, 100), Decimal("1.4"), "ratio", "{first} / {second}"),
        (
            "percentage_change",
            (100, 140),
            Decimal("40"),
            "percent",
            "({second} - {first}) / {first} * 100",
        ),
    ],
)
def test_supported_calculations_are_exact_and_auditable(
    operation: str,
    values: tuple[int, int],
    expected: Decimal,
    unit: str,
    formula: str,
) -> None:
    first = _evidence("ev_111111111111111111111111", values[0])
    second = _evidence("ev_222222222222222222222222", values[1])

    result = calculate_evidence(
        EvidenceCalculationRequest(
            operation=operation,
            evidence_references=[first.reference, second.reference],
        ),
        {
            first.reference: ("monthly_total_revenue", first),
            second.reference: ("monthly_total_revenue", second),
        },
        current_store_id=2,
        now=NOW,
    )

    assert result.formula == formula.format(first=first.reference, second=second.reference)
    assert result.exact_result == expected
    assert result.unit == unit
    assert result.cannot_calculate_reason is None


@pytest.mark.parametrize(
    ("request_payload", "available", "reason"),
    [
        (
            {
                "operation": "ratio",
                "evidence_references": [
                    "ev_111111111111111111111111",
                    "ev_222222222222222222222222",
                ],
            },
            {
                "first": _evidence("ev_111111111111111111111111", 140),
                "second": _evidence("ev_222222222222222222222222", 0),
            },
            "zero_denominator",
        ),
        (
            {
                "operation": "sum",
                "evidence_references": [
                    "ev_111111111111111111111111",
                    "ev_222222222222222222222222",
                ],
            },
            {
                "first": _evidence("ev_111111111111111111111111", 140, unit="EUR"),
                "second": _evidence("ev_222222222222222222222222", 20, unit="day"),
            },
            "incompatible_units",
        ),
        (
            {
                "operation": "difference",
                "evidence_references": [
                    "ev_111111111111111111111111",
                    "ev_999999999999999999999999",
                ],
            },
            {"first": _evidence("ev_111111111111111111111111", 140)},
            "reference_not_current",
        ),
        (
            {
                "operation": "difference",
                "evidence_references": [
                    "ev_111111111111111111111111",
                    "ev_222222222222222222222222",
                ],
            },
            {
                "first": _evidence(
                    "ev_111111111111111111111111",
                    140,
                    queried_at=datetime(2026, 7, 28, 9, 30, tzinfo=timezone.utc),
                ),
                "second": _evidence("ev_222222222222222222222222", 100),
            },
            "stale_reference",
        ),
        (
            {
                "operation": "difference",
                "evidence_references": [
                    "ev_111111111111111111111111",
                    "ev_222222222222222222222222",
                ],
            },
            {
                "first": _evidence("ev_111111111111111111111111", 140, store_id=9),
                "second": _evidence("ev_222222222222222222222222", 100),
            },
            "unauthorized_reference",
        ),
        (
            {
                "operation": "difference",
                "evidence_references": [
                    "ev_111111111111111111111111",
                    "ev_222222222222222222222222",
                ],
            },
            {
                "first": _evidence("ev_111111111111111111111111", None, failed=True),
                "second": _evidence("ev_222222222222222222222222", 100),
            },
            "input_unavailable",
        ),
        (
            {
                "operation": "difference",
                "evidence_references": [
                    "ev_111111111111111111111111",
                    "ev_222222222222222222222222",
                ],
            },
            {
                "first": _evidence("ev_111111111111111111111111", None),
                "second": _evidence("ev_222222222222222222222222", 100),
            },
            "input_unavailable",
        ),
    ],
)
def test_calculation_failures_are_closed_and_explain_why(
    request_payload: dict[str, object],
    available: dict[str, NativeEvidenceEnvelope],
    reason: str,
) -> None:
    by_reference = {
        evidence.reference: ("monthly_total_revenue", evidence) for evidence in available.values()
    }

    result = calculate_evidence(
        EvidenceCalculationRequest.model_validate(request_payload),
        by_reference,
        current_store_id=2,
        now=NOW,
    )

    assert result.formula is None
    assert result.exact_result is None
    assert result.unit is None
    assert result.cannot_calculate_reason == reason


@pytest.mark.parametrize(
    "prohibited",
    [
        {"user_id": 1},
        {"store_id": 2},
        {"sql": "select * from daily_records"},
        {"field": "monthly_total_revenue"},
        {"expression": "open('backup.sqlite3')"},
        {"table": "users"},
    ],
)
def test_calculation_request_rejects_scope_and_arbitrary_query_fields(
    prohibited: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        EvidenceCalculationRequest.model_validate(
            {
                "operation": "difference",
                "evidence_references": [
                    "ev_111111111111111111111111",
                    "ev_222222222222222222222222",
                ],
                **prohibited,
            }
        )
