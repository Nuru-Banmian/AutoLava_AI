from datetime import date, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from app.agent.contracts import (
    BusinessEvidenceRequest,
    DailyLedgerExtremeResult,
    EvidenceRequest,
    OpenBusinessRecordsAction,
)

BUSINESS_REQUEST_ADAPTER = TypeAdapter(BusinessEvidenceRequest)


def test_evidence_request_has_at_most_one_bounded_group_position() -> None:
    request = EvidenceRequest(
        kind="business_metrics",
        metric="income_category_amount",
        group_by="income_category",
    )

    assert request.group_by == "income_category"
    with pytest.raises(ValidationError):
        BUSINESS_REQUEST_ADAPTER.validate_python(
            {
                "kind": "business_metrics",
                "metric": "income_category_amount",
                "group_by": ["income_category", "date"],
            }
        )


@pytest.mark.parametrize(
    ("group_by", "metric"),
    (
        ("date", "daily_ledger_revenue"),
        ("calendar_month", "daily_ledger_revenue"),
        ("calendar_year", "daily_ledger_revenue"),
        ("income_category", "income_category_amount"),
        ("recorded_weather", "daily_ledger_revenue"),
        ("weekday", "daily_ledger_revenue"),
        ("operating_status", "daily_ledger_revenue"),
    ),
)
def test_evidence_request_accepts_each_whitelisted_group(
    group_by: str,
    metric: str,
) -> None:
    request = EvidenceRequest(
        kind="business_metrics",
        metric=metric,
        group_by=group_by,
    )

    assert request.group_by == group_by


def test_evidence_request_accepts_bounded_deterministic_filters() -> None:
    request = EvidenceRequest.model_validate(
        {
            "kind": "business_metrics",
            "metric": "daily_ledger_revenue",
            "filters": {
                "income_categories": ["  Carta  ", "现金"],
                "recorded_weather": ["晴", "多云"],
                "weekdays": ["星期一", "星期日"],
                "operating_statuses": ["营业", "提前休息"],
            },
        }
    )

    assert request.filters is not None
    assert request.filters.income_categories == ["Carta", "现金"]
    assert request.filters.weekdays == ["星期一", "星期日"]


@pytest.mark.parametrize(
    "filters",
    (
        {"income_categories": [f"分类 {index}" for index in range(11)]},
        {
            "income_categories": [f"分类 {index}" for index in range(6)],
            "recorded_weather": [f"天气 {index}" for index in range(6)],
            "weekdays": [
                "星期一",
                "星期二",
                "星期三",
                "星期四",
                "星期五",
                "星期六",
            ],
            "operating_statuses": ["营业", "休息", "提前休息"],
        },
        {"weekdays": ["周一"]},
        {"operating_statuses": ["天气停业"]},
        {"event": ["促销"]},
    ),
)
def test_evidence_request_rejects_excessive_or_non_whitelisted_filters(
    filters: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        EvidenceRequest.model_validate(
            {
                "kind": "business_metrics",
                "metric": "daily_ledger_revenue",
                "filters": filters,
            }
        )


def test_daily_ledger_extreme_is_bounded_to_one_direction_and_compatible_shape() -> None:
    request = EvidenceRequest(
        kind="business_metrics",
        metric="daily_ledger_revenue",
        extreme="lowest",
    )

    assert request.extreme == "lowest"
    for invalid in (
        {
            "kind": "business_metrics",
            "metric": "operating_days",
            "extreme": "highest",
        },
        {
            "kind": "business_metrics",
            "metric": "daily_ledger_revenue",
            "extreme": ["highest", "lowest"],
        },
        {
            "kind": "business_metrics",
            "metric": "daily_ledger_revenue",
            "extreme": "highest",
            "group_by": "date",
        },
    ):
        with pytest.raises(ValidationError):
            EvidenceRequest.model_validate(invalid)


def test_daily_ledger_extreme_preserves_every_tied_operating_date() -> None:
    start = date(2025, 1, 1)
    tied_dates = [start + timedelta(days=offset) for offset in range(401)]

    result = DailyLedgerExtremeResult(
        extreme="lowest",
        daily_ledger_revenue=0,
        dates=tied_dates,
    )

    assert result.dates == tied_dates


def test_evidence_metric_whitelist_fails_closed() -> None:
    with pytest.raises(ValidationError):
        EvidenceRequest(
            kind="business_metrics",
            metric="arbitrary_sql_metric",
        )


def test_daily_ledger_request_requires_one_exact_date_and_no_metric_or_period() -> None:
    request = BUSINESS_REQUEST_ADAPTER.validate_python(
        {"kind": "daily_ledger", "date": "2026-07-05"}
    )

    assert request.date.isoformat() == "2026-07-05"
    for invalid in (
        {"kind": "daily_ledger"},
        {
            "kind": "daily_ledger",
            "date": "2026-07-05",
            "metric": "monthly_total_revenue",
        },
        {
            "kind": "daily_ledger",
            "date": "2026-07-05",
            "period": {"kind": "calendar_month", "year": 2026, "month": 7},
        },
        {"kind": "business_metrics", "metric": "daily_ledger"},
    ):
        with pytest.raises(ValidationError):
            BUSINESS_REQUEST_ADAPTER.validate_python(invalid)


@pytest.mark.parametrize(
    "action",
    (
        {
            "type": "open_business_records",
            "start_month": "2026-07",
            "end_month": "2026-06",
        },
        {
            "type": "open_business_records",
            "start_month": "1999-12",
            "end_month": "2026-06",
        },
        {
            "type": "open_business_records",
            "start_month": "2026-6",
            "end_month": "2026-07",
        },
        {
            "type": "arbitrary_navigation",
            "start_month": "2026-06",
            "end_month": "2026-07",
        },
        {
            "type": "open_business_records",
            "start_month": "2026-06",
            "end_month": "2026-07",
            "url": "/database?store_id=999",
        },
    ),
)
def test_business_record_action_rejects_invalid_or_expanded_parameters(
    action: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        OpenBusinessRecordsAction.model_validate(action)


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
def test_business_evidence_request_rejects_model_owned_scope_and_query_fields(
    untrusted_field: str,
) -> None:
    request = {
        "kind": "business_metrics",
        "metric": "monthly_total_revenue",
        untrusted_field: "untrusted",
    }

    with pytest.raises(ValidationError):
        BUSINESS_REQUEST_ADAPTER.validate_python(request)


@pytest.mark.parametrize(
    "period",
    (
        {"kind": "exact_date", "date": "1999-12-31"},
        {
            "kind": "custom_date_range",
            "start": "2026-01-01",
            "end": "2201-01-01",
        },
        {
            "kind": "custom_date_range",
            "start": "2025-01-01",
            "end": "2026-02-05",
        },
    ),
)
def test_business_evidence_request_bounds_exact_and_custom_dates(
    period: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        BUSINESS_REQUEST_ADAPTER.validate_python(
            {
                "kind": "business_metrics",
                "metric": "monthly_total_revenue",
                "period": period,
            }
        )
