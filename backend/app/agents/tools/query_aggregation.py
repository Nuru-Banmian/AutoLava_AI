"""Projected business metrics, sharing state and display rules with analytics."""
from collections import defaultdict
from calendar import monthrange
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.models.ledger import StoreDailyRecord
from app.services.business_metrics import rounded_average
from app.services.ledger_statistics import OPERATING_STATES, period_coverage, statistical_records


def ledger_dependencies(metrics):
    fields = {"date", "is_open"}
    if set(metrics) - {"operating_days", "total_wash_count"}:
        fields.add("daily_revenue")
    if set(metrics) & {"total_wash_count", "average_revenue_per_car"}:
        fields.add("wash_count")
    return fields


async def load_ledger(session, conditions, metrics, extra_fields=(), *, wash_count_enabled=True):
    active = metrics if wash_count_enabled else [m for m in metrics if m not in ("total_wash_count", "average_revenue_per_car")]
    fields = ledger_dependencies(active) | set(extra_fields)
    statement = select(*[getattr(StoreDailyRecord, key).label(key) for key in sorted(fields)])
    return [SimpleNamespace(**row) for row in
            (await session.execute(statement.where(*conditions))).mappings()]


def ledger_summary(records, metrics, store, start, end):
    statistical = statistical_records(records)
    operating = [r for r in records if r.is_open in OPERATING_STATES]
    coverage = period_coverage(records, start, end)
    values, statuses, denominators = {}, {}, {}
    revenues = [r.daily_revenue for r in statistical] if any(
        hasattr(r, "daily_revenue") for r in records) else []
    total = sum(revenues) if statistical and revenues else None
    covered = [r for r in operating if getattr(r, "wash_count", None) is not None]
    wash = sum(r.wash_count for r in covered) if covered else None
    if set(metrics) & {"total_wash_count", "average_revenue_per_car"}:
        coverage.update({
            "wash_count_covered_days": len(covered) if store.wash_count_enabled else None,
            "wash_count_missing_operating_days": len(operating) - len(covered)
            if store.wash_count_enabled else None,
            "wash_count_status": ("disabled" if not store.wash_count_enabled else
                                  "no_operating_days" if not operating else
                                  "missing" if not covered else
                                  "complete" if len(covered) == len(operating) else "partial"),
        })
    for metric in metrics:
        reason = None
        if metric in ("total_revenue", "daily_ledger_revenue"):
            value = total
        elif metric == "operating_days":
            value = len(operating)
            if not statistical:
                reason = "no_statistical_ledger"
        elif metric == "average_ledger_revenue":
            denominators[metric] = len(operating)
            value = rounded_average(sum(r.daily_revenue for r in operating), len(operating)) if operating else None
            if not operating:
                reason = "no_operating_days"
        elif metric in ("min_revenue", "max_revenue"):
            value = (min(revenues) if metric == "min_revenue" else max(revenues)) if revenues else None
        elif metric in ("total_wash_count", "average_revenue_per_car"):
            value = wash
            if not store.wash_count_enabled:
                value, reason = None, "wash_count_disabled"
            elif not operating:
                value, reason = None, "no_operating_days"
            elif wash is None:
                reason = "no_wash_count"
            elif metric == "average_revenue_per_car":
                denominators[metric] = wash
                value = rounded_average(sum(r.daily_revenue for r in covered), wash) if wash else None
                if not wash:
                    reason = "zero_wash_count"
        else:
            raise ValueError("Unknown ledger metric")
        values[metric] = value
        statuses[metric] = reason or ("available" if value is not None else "no_statistical_ledger")
    return {"metrics": values, "metric_status": statuses, "denominators": denominators,
            "coverage": coverage}


def dimension(record, name):
    if name == "day":
        return record.date.isoformat()
    if name == "week":
        return (record.date - timedelta(days=record.date.weekday())).isoformat()
    if name == "month":
        return record.date.strftime("%Y-%m")
    if name == "weekday":
        return record.date.weekday()
    if name == "weather":
        return record.weather or "未记录"
    raise ValueError("Unknown grouping dimension")


def group_bounds(key, groups, start, end):
    from datetime import date
    for name, value in zip(groups, key):
        if name == "day":
            return date.fromisoformat(value), date.fromisoformat(value)
        if name == "week":
            first = date.fromisoformat(value)
            return max(start, first), min(end, first + timedelta(days=6))
        if name == "month":
            first = date.fromisoformat(value + "-01")
            return max(start, first), min(end, first.replace(day=monthrange(first.year, first.month)[1]))
    return start, end


def ledger_groups(records, target, store, start, end):
    if not target.group_by:
        return []
    buckets = defaultdict(list)
    for record in records:
        buckets[tuple(dimension(record, name) for name in target.group_by)].append(record)
    if len(target.group_by) == 1 and target.group_by[0] in ("day", "week", "month") and not target.filters:
        current = start
        while current <= end:
            key = dimension(SimpleNamespace(date=current), target.group_by[0])
            buckets.setdefault((key,), [])
            if target.group_by[0] == "day":
                current += timedelta(days=1)
            elif target.group_by[0] == "week":
                current += timedelta(days=7 - current.weekday())
            else:
                current += timedelta(days=monthrange(current.year, current.month)[1] - current.day + 1)
    rows = []
    for key, values in sorted(buckets.items(), key=lambda pair: str(pair[0])):
        first, last = group_bounds(key, target.group_by, start, end)
        summary = ledger_summary(values, target.metrics, store, first, last)
        if set(target.group_by) & {"weather", "weekday"}:
            summary["coverage"]["scope"] = "matched_group"
            summary["coverage"]["interval_days"] = None
            summary["coverage"]["missing_record_days"] = None
        row = {**dict(zip(target.group_by, key)), **summary}
        if target.group_by == ["day"]:
            row["state"] = values[0].is_open if values else "未录入"
        rows.append(row)
    return rows
