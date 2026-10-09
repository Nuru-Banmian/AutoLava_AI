"""Historical classification metrics over the exact target's matched rows."""

from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import select

from app.agents.tools.query_aggregation import dimension, group_bounds
from app.models.ledger import DailyIncomeItem, StoreDailyRecord
from app.services.business_metrics import rounded_percent
from app.services.ledger_statistics import period_coverage, statistical_records

BASE_SCOPE = "same_filters_and_non_category_groups_by_include_in_total"


def _category(record):
    return record.category_id, record.category_name, record.include_in_total


def _amount_bases(records):
    bases = {True: 0, False: 0}
    for record in statistical_records(records):
        bases[record.include_in_total] += record.amount
    return bases


def _summary(records, metrics, bases, start, end):
    statistical = statistical_records(records)
    amount = sum(record.amount for record in statistical) if statistical else None
    income_statuses = {record.include_in_total for record in statistical}
    values, statuses, denominators = {}, {}, {}
    for metric in metrics:
        value, reason = amount, None
        if metric == "share_percent":
            if len(income_statuses) > 1:
                value, reason = None, "mixed_income_and_other_data"
                denominators[metric] = {"included_income": bases[True], "other_data": bases[False]}
            else:
                base = bases[next(iter(income_statuses))] if income_statuses else 0
                denominators[metric] = base
                value = rounded_percent(amount, base) if amount is not None else None
                if base == 0:
                    reason = "zero_denominator" if statistical else "no_statistical_items"
        elif metric != "amount":
            raise ValueError("Unknown classification metric")
        values[metric] = value
        statuses[metric] = reason or ("available" if value is not None else "no_statistical_items")
    dates = {record.date: record for record in records}
    coverage = period_coverage(list(dates.values()), start, end)
    coverage.update({"scope": "matched_income_item_dates", "interval_days": None,
                     "missing_record_days": None, "source_rows": len(records), "base_scope": BASE_SCOPE,
                     "included_income_base": bases[True], "other_data_base": bases[False]})
    return {"metrics": values, "metric_status": statuses,
            "denominators": denominators, "coverage": coverage}


async def aggregate_categories(session, store, target, start, end, conditions):
    """Keep filters before both numerator and denominator; no ledger revenue/settlement read."""
    record, item = StoreDailyRecord, DailyIncomeItem
    columns = {"date": record.date, "is_open": record.is_open,
               "amount": item.amount, "include_in_total": item.include_in_total}
    if "category" in target.group_by:
        columns.update({"category_id": item.category_id, "category_name": item.category_name})
    if "weather" in target.group_by:
        columns["weather"] = record.weather
    statement = select(*[column.label(name) for name, column in columns.items()]).select_from(record).join(
        item, item.record_id == record.id).where(*conditions)
    records = [SimpleNamespace(**row) for row in (await session.execute(statement)).mappings()]
    summary = _summary(records, target.metrics, _amount_bases(records), start, end)
    rows = []
    if target.group_by:
        buckets = defaultdict(list)
        base_buckets = defaultdict(list)
        for value in records:
            key = tuple(_category(value) if name == "category" else dimension(value, name)
                        for name in target.group_by)
            buckets[key].append(value)
            base_key = tuple(item for name, item in zip(target.group_by, key) if name != "category")
            base_buckets[base_key].append(value)
        bases = {key: _amount_bases(values) for key, values in base_buckets.items()}
        for key, values in sorted(buckets.items(), key=lambda pair: str(pair[0])):
            base_key = tuple(value for name, value in zip(target.group_by, key) if name != "category")
            first, last = group_bounds(key, target.group_by, start, end)
            row = _summary(values, target.metrics, bases[base_key], first, last)
            for name, value in zip(target.group_by, key):
                if name == "category":
                    category_id, category_name, include_in_total = value
                    row.update({"category": category_name, "category_id": category_id,
                                "category_name": category_name, "include_in_total": include_in_total})
                else:
                    row[name] = value
            rows.append(row)
    matched = len(rows) if target.group_by else len(records)
    return {**summary, "rows": rows, "source_count": len(records), "matched_count": matched,
            "selected_count": matched}
