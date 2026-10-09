"""Shared state rules: recorded dates and statistical dates are distinct."""

from datetime import date

from app.models.ledger import StoreDailyRecord

OPERATING_STATES = frozenset({"营业", "提前休息"})
STATISTICAL_STATES = OPERATING_STATES | {"休息"}


def statistical_records(records):
    return [record for record in records if record.is_open in STATISTICAL_STATES]


def period_coverage(records: list[StoreDailyRecord], start: date, end: date) -> dict:
    statistical_days = sum(record.is_open in STATISTICAL_STATES for record in records)
    interval_days = max(0, (end - start).days + 1)
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "record_days": len(records), "interval_days": interval_days,
        "statistical_days": statistical_days,
        "unreported_days": sum(record.is_open == "未统计" for record in records),
        "operating_days": sum(record.is_open in OPERATING_STATES for record in records),
        "rest_days": sum(record.is_open == "休息" for record in records),
        "missing_record_days": interval_days - len(records),
    }
