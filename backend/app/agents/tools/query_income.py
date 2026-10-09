"""Projected month-grain income; settlement amounts are never assigned to a day."""

from calendar import monthrange
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select

from app.agents.tools.query_aggregation import ledger_summary, load_ledger
from app.agents.tools.store_catalog import local_today
from app.models.ledger import DailyIncomeItem, StoreDailyRecord
from app.models.settlement import SettlementRecord
from app.services.business_metrics import rounded_average, rounded_percent
from app.services.ledger_statistics import period_coverage, statistical_records

COMPONENT_FILTERS = {"category_id", "category_name", "include_in_total"}
SETTLEMENT_METRICS = {"confirmed_settlement_income", "total_income", "monthly_average_income"}


def month_key(day):
    return day.strftime("%Y-%m")


def periods(start, end, dimension):
    current = start.replace(day=1) if dimension == "month" else date(start.year, 1, 1)
    while current <= end:
        if dimension == "month":
            last = current.replace(day=monthrange(current.year, current.month)[1])
            next_period = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
            key = month_key(current)
        else:
            last, next_period = date(current.year, 12, 31), date(current.year + 1, 1, 1)
            key = str(current.year)
        yield key, max(start, current), min(end, last)
        current = next_period


def income_ledger_metrics(metrics):
    selected = []
    for metric in metrics:
        dependencies = ({"daily_ledger_revenue", "operating_days"} if metric == "monthly_average_income"
                        else {"daily_ledger_revenue"} if metric == "total_income"
                        else set() if metric == "confirmed_settlement_income" else {metric})
        selected.extend(sorted(dependencies - set(selected)))
    return selected


async def settlements_by_month(session, store_id, start, end):
    statement = select(SettlementRecord.opening_month, func.sum(SettlementRecord.amount)).where(
        SettlementRecord.store_id == store_id, SettlementRecord.status == "confirmed",
        SettlementRecord.opening_month >= start.replace(day=1),
        SettlementRecord.opening_month <= end.replace(day=1),
    ).group_by(SettlementRecord.opening_month)
    return {month_key(month): int(amount) for month, amount in (await session.execute(statement)).tuples()}


def settlement_total(settlements, start, end):
    return sum(amount for month, amount in settlements.items()
               if month_key(start) <= month <= month_key(end))


def monthly_range(start, end, today):
    return (start.year, start.month) == (end.year, end.month) and start.day == 1 and (
        end.day == monthrange(end.year, end.month)[1] or
        (end == today and (end.year, end.month) == (today.year, today.month)))


def income_summary(records, settlements, metrics, store, start, end, *, filtered=False):
    ledger = ledger_summary(records, income_ledger_metrics(metrics), store, start, end)
    values, statuses, denominators = {}, {}, {}
    confirmed = settlement_total(settlements, start, end)
    ledger_total = ledger["metrics"].get("daily_ledger_revenue")
    total = (ledger_total or 0) + confirmed if ledger_total is not None or confirmed else None
    for metric in metrics:
        reason = None
        if metric == "confirmed_settlement_income":
            value = confirmed
        elif metric == "total_income":
            value = total
            reason = "no_statistical_ledger" if value is None else None
        elif metric == "monthly_average_income":
            days = ledger["metrics"]["operating_days"]
            denominators[metric] = days
            value = None
            if filtered:
                reason = "filtered_monthly_range"
            elif not monthly_range(start, end, local_today(store)):
                reason = "invalid_monthly_range"
            elif not days:
                reason = "no_operating_days"
            elif total is not None:
                value = rounded_average(total, days)
        else:
            value = ledger["metrics"][metric]
            reason = ledger["metric_status"][metric]
            if metric in ledger["denominators"]:
                denominators[metric] = ledger["denominators"][metric]
        values[metric], statuses[metric] = value, reason or "available"
    return {"metrics": values, "metric_status": statuses, "denominators": denominators,
            "coverage": ledger["coverage"]}


def component_matches(component, filters):
    for item in filters:
        if item.field not in COMPONENT_FILTERS:
            continue
        value = component[item.field]
        if item.op == "eq" and value != item.value:
            return False
        if item.op == "in" and value not in item.value:
            return False
        if item.op == "contains" and (value is None or item.value not in value):
            return False
        if item.op == "gte" and (value is None or value < item.value):
            return False
        if item.op == "lte" and (value is None or value > item.value):
            return False
        if item.op == "is_null" and value is not None:
            return False
        if item.op == "not_null" and value is None:
            return False
    return True


def composition_dependencies(target):
    """Use historical flags and synthetic identities to plan income dependencies."""
    flag_filters = [item for item in target.filters if item.field == "include_in_total"]
    income_possible = component_matches({"include_in_total": True}, flag_filters)
    category_selected = any(item.field in COMPONENT_FILTERS for item in target.filters)
    other_possible = category_selected and component_matches({"include_in_total": False}, flag_filters)
    share = "share_percent" in target.metrics
    income_base, other_base = share and income_possible, share and other_possible
    synthetic = {"category_id": None, "include_in_total": True}
    remainder = component_matches({**synthetic, "category_name": "未分类营业额"}, target.filters)
    settlement = component_matches({**synthetic, "category_name": "公司结算"}, target.filters)
    return {"remainder": remainder, "settlements": settlement or income_base,
            "ledger_revenue": remainder or income_base,
            "income_base": income_base, "other_base": other_base}


def component_result(component, amount, metrics, denominator, scope):
    values, statuses, denominators = {}, {}, {}
    for metric in metrics:
        value = amount if metric == "amount" else rounded_percent(amount, denominator)
        values[metric] = value
        statuses[metric] = "available" if value is not None else "zero_denominator"
        if metric == "share_percent":
            denominators[metric] = denominator
    return {**component, "metrics": values, "metric_status": statuses,
            "denominators": denominators, "denominator_scope": scope}


async def income_components(session, conditions, records, settlements, *, remainder=True):
    statement = select(StoreDailyRecord.date, DailyIncomeItem.category_id,
                       DailyIncomeItem.category_name, DailyIncomeItem.include_in_total,
                       DailyIncomeItem.amount).select_from(StoreDailyRecord).join(
                           DailyIncomeItem, DailyIncomeItem.record_id == StoreDailyRecord.id).where(*conditions)
    components, classified = [], defaultdict(int)
    for row in (await session.execute(statement)).mappings():
        item = dict(row)
        item["source"] = "income_category" if item["include_in_total"] else "other_data"
        components.append(item)
        if item["include_in_total"]:
            classified[item["date"]] += item["amount"]
    for record in statistical_records(records) if remainder else []:
        remainder = record.daily_revenue - classified[record.date]
        if remainder:
            components.append({"date": record.date, "category_id": None,
                               "category_name": "未分类营业额", "include_in_total": True,
                               "source": "unclassified_revenue", "amount": remainder})
    for month, amount in settlements.items():
        components.append({"date": date.fromisoformat(month + "-01"), "category_id": None,
                           "category_name": "公司结算", "include_in_total": True,
                           "source": "confirmed_settlement", "amount": amount})
    return components


async def aggregate_income(session, store, target, start: date, end: date, conditions: list) -> dict:
    composition = target.domain == "income_composition"
    dependencies = composition_dependencies(target) if composition else None
    ledger_metrics = (["daily_ledger_revenue"] if dependencies["ledger_revenue"] else []) if composition else income_ledger_metrics(target.metrics)
    records = await load_ledger(session, conditions, ledger_metrics,
                                wash_count_enabled=store.wash_count_enabled)
    uses_settlements = dependencies["settlements"] if composition else bool(set(target.metrics) & SETTLEMENT_METRICS)
    settlements = (await settlements_by_month(session, store.id, start, end)
                   if uses_settlements else {})
    dimension = next((d for d in target.group_by if d in ("month", "year")), None)
    spans = list(periods(start, end, dimension)) if dimension else [(None, start, end)]
    common_notes = []
    if uses_settlements:
        common_notes.append("已确认公司结算按重叠开票月份整笔纳入，关闭功能仍保留历史；不分摊到日或周。")
        if target.filters:
            common_notes.append("台账筛选仅约束台账；公司结算没有相同日粒度筛选，仍按重叠开票月整笔纳入。")
    if not composition:
        result = income_summary(records, settlements, target.metrics, store, start, end,
                                filtered=bool(target.filters))
        result["rows"] = []
        if dimension:
            for key, first, last in spans:
                selected = [record for record in records if first <= record.date <= last]
                result["rows"].append({dimension: key, **income_summary(
                    selected, settlements, target.metrics, store, first, last,
                    filtered=bool(target.filters))})
        result["matched_count"] = len(result["rows"]) if dimension else len(records)
    else:
        components = await income_components(session, conditions, records, settlements,
                                             remainder=dependencies["remainder"])
        category_selected = any(item.field in COMPONENT_FILTERS for item in target.filters)
        selected = [c for c in components if (c["include_in_total"] or category_selected)
                    and component_matches(c, target.filters)]
        only_other_filter = any(item.field == "include_in_total" and (
            (item.op == "eq" and item.value is False) or (item.op == "in" and item.value == [False]))
            for item in target.filters)
        select_other = (bool(selected) and all(not c["include_in_total"] for c in selected)) or only_other_filter
        mixed = any(c["include_in_total"] for c in selected) and any(not c["include_in_total"] for c in selected)
        if mixed and dimension and "category" not in target.group_by:
            raise ValueError("Income and other data require separate category groups")
        income_total = (income_summary(records, settlements, ["total_income"], store, start, end)["metrics"]["total_income"]
                        if dependencies["income_base"] else None)
        other_total = (sum(c["amount"] for c in components if not c["include_in_total"])
                       if statistical_records(records) else None)
        denominator = other_total if select_other else income_total
        known = bool(statistical_records(records)) or (not select_other and bool(settlement_total(settlements, start, end)))
        amount = sum(c["amount"] for c in selected) if selected or known else None
        result = component_result({}, amount, target.metrics, denominator or 0,
                                  "categorical_other" if select_other else "total_income")
        if mixed:
            result["denominator_scope"] = "separate_income_and_other_data"
            if "share_percent" in target.metrics:
                result["metrics"]["share_percent"] = None
                result["metric_status"]["share_percent"] = "incompatible_income_basis"
                result["denominators"]["share_percent"] = {
                    "total_income": income_total, "categorical_other": other_total}
        if amount is None:
            result["metric_status"] = {metric: "no_statistical_ledger" for metric in target.metrics}
        result["coverage"] = period_coverage(records, start, end)
        result["rows"] = []
        for key, first, last in spans:
            totals = defaultdict(int)
            for component in selected:
                # Settlements in a partial month remain a whole-month component.
                component_day = component["date"]
                in_span = (month_key(first) <= month_key(component_day) <= month_key(last)
                           if component["source"] == "confirmed_settlement" else first <= component_day <= last)
                if in_span:
                    identity = tuple(component[field] for field in
                                     ("category_id", "category_name", "include_in_total", "source"))
                    totals[identity] += component["amount"]
            selected_records = [r for r in records if first <= r.date <= last]
            span_total = (income_summary(selected_records, settlements, ["total_income"], store, first, last)["metrics"]["total_income"]
                          if dependencies["income_base"] else None)
            other_denominator = sum(c["amount"] for c in components if not c["include_in_total"] and first <= c["date"] <= last)
            if dimension and "category" not in target.group_by:
                denominator = (other_denominator if statistical_records(selected_records) else None) if select_other else span_total
                known = bool(statistical_records(selected_records)) or (not select_other and bool(settlement_total(settlements, first, last)))
                amount = sum(totals.values()) if totals or known else None
                row = component_result({dimension: key}, amount, target.metrics, denominator or 0,
                                       "categorical_other" if select_other else "total_income")
                if amount is None:
                    row["metric_status"] = {metric: "no_statistical_ledger" for metric in target.metrics}
                row["coverage"] = period_coverage(selected_records, first, last)
                result["rows"].append(row)
                continue
            for identity, amount in sorted(totals.items(), key=lambda item: (item[0][3], str(item[0][0]), item[0][1])):
                component = dict(zip(("category_id", "category_name", "include_in_total", "source"), identity, strict=True))
                if dimension:
                    component[dimension] = key
                component["category"] = component["category_name"]
                result["rows"].append(component_result(component, amount, target.metrics,
                    other_denominator if not component["include_in_total"] else span_total or 0,
                    "categorical_other" if not component["include_in_total"] else "total_income"))
        result["matched_count"] = len(result["rows"])
        common_notes.append("收入构成只含计入营业额的历史分类、未分类营业额和已确认结算；其他数据须单独选择，不属于成本或利润。")
    result["selected_count"] = result["matched_count"]
    if common_notes:
        result["notes"] = common_notes
    if uses_settlements:
        result["settlement_months"] = sorted(settlements)
        result["settlement_scope"] = {"start_month": month_key(start), "end_month": month_key(end)}
        result["partial_months"] = [key for key, first, last in periods(start, end, "month")
                                    if first.day != 1 or last.day != monthrange(last.year, last.month)[1]]
    return result
