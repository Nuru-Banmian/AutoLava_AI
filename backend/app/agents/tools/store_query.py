"""Read-only projected queries; no ORM business object or settlement loading."""
import json
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import Integer, cast, func, select, text

from app.agents.tools.query_results import (
    capacity_receipt, materialize, message_size, page, serialized_size,
)

from app.agents.tools.query_dates import DateRange, comparison_range, resolve_range
from app.agents.tools.query_aggregation import ledger_groups, ledger_summary, load_ledger
from app.agents.tools.query_definitions import GROUPS, METRICS
from app.agents.tools.store_catalog import ITEM_FIELDS, date_snapshot, fields_for, local_today, version
from app.models.identity import Store
from app.models.ledger import DailyIncomeItem, StoreDailyRecord
from app.services.business_metrics import rounded_percent


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Continuation(StrictInput):
    result_ref: str = Field(min_length=32, max_length=32)
    cursor: str = Field(min_length=1, max_length=128)
    page_size: int = Field(default=50, ge=1, le=200)


class QueryInput(StrictInput):
    catalog_version: str | None = Field(default=None, min_length=1, max_length=64)
    targets: list[dict[str, Any]] = Field(default_factory=list, max_length=6, description=(
        "Unique id, domain daily_ledger/income_items/monthly_income/income_composition, fields or metrics (1-16), range: start/end OR preset"
        "(+n for last_n_*; +base for same_period_last_year) OR all_history:true. Omit range=month to date. "
        "Optional filters:[{field,op,value}], order_by:[{field,direction:asc/desc}], top_n:1-100. "
        "Choose fields OR metrics; group_by uses catalog dimensions. compare: {preset:previous_period/"
        "same_period_last_year} OR {range:{start,end/preset}}. page_size:1-200 (default 50)."))
    continuations: list[Continuation] = Field(default_factory=list, max_length=6,
        description="Continue immutable results with result_ref, cursor and optional page_size only; omit catalog_version/targets.")

    @model_validator(mode="after")
    def unique_ids(self):
        if bool(self.targets) == bool(self.continuations):
            raise ValueError("Choose new queries or continuations")
        if self.continuations:
            if self.catalog_version is not None or len({c.result_ref for c in self.continuations}) != len(self.continuations):
                raise ValueError("Continuation cannot change catalog or repeat references")
            return self
        if self.catalog_version is None:
            raise ValueError("New queries require catalog_version")
        ids = [target.get("id") for target in self.targets]
        if any(not isinstance(value, str) or not 1 <= len(value) <= 64 for value in ids):
            raise ValueError("Each target requires an id")
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate target id")
        return self


class Filter(StrictInput):
    field: str
    op: Literal["eq", "in", "gte", "lte", "contains", "is_null", "not_null"]
    value: Any = None


class Order(StrictInput):
    field: str
    direction: Literal["asc", "desc"] = "asc"


class Comparison(StrictInput):
    preset: Literal["previous_period", "same_period_last_year"] | None = None
    range: DateRange | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.preset is not None and self.range is not None:
            raise ValueError("Choose comparison preset or explicit range")
        return self


class QueryTarget(StrictInput):
    id: str = Field(min_length=1, max_length=64)
    domain: Literal["daily_ledger", "income_items", "monthly_income", "income_composition"]
    range: DateRange | None = None
    fields: list[str] = Field(default_factory=list, max_length=16)
    metrics: list[str] = Field(default_factory=list, max_length=16)
    group_by: list[str] = Field(default_factory=list, max_length=2)
    filters: list[Filter] = Field(default_factory=list, max_length=8)
    order_by: list[Order] = Field(default_factory=list, max_length=2)
    top_n: int | None = Field(default=None, ge=1, le=100)
    compare: Comparison | None = None
    page_size: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def supported(self):
        if bool(self.fields) == bool(self.metrics) or len(self.fields) + len(self.metrics) > 16:
            raise ValueError("Choose detail fields or aggregate metrics")
        if self.fields and (self.group_by or self.compare or self.domain not in ("daily_ledger", "income_items")):
            raise ValueError("Details cannot be grouped")
        if (not set(self.group_by).issubset(GROUPS[self.domain])
                or len(set(self.group_by)) != len(self.group_by)
                or len(set(self.group_by) & {"day", "week", "month", "year"}) > 1):
            raise ValueError("Invalid grouping combination")
        if self.metrics and not set(self.metrics).issubset(METRICS[self.domain]):
            raise ValueError("Unknown metric")
        if self.metrics and not self.group_by and self.domain != "income_composition" and (self.top_n or self.order_by):
            raise ValueError("Aggregate ranking requires grouped rows")
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("Duplicate metric")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("Duplicate field")
        if len({o.field for o in self.order_by}) != len(self.order_by):
            raise ValueError("Duplicate ordering")
        return self


class QueryError(ValueError):
    def __init__(self, code, message, **metadata):
        self.code, self.message, self.metadata = code, message, metadata


def field_columns(domain):
    r, i = StoreDailyRecord, DailyIncomeItem
    columns = {key: getattr(r, key) for key in ("date", "is_open", "daily_revenue", "wash_count", "weather", "activity")}
    columns["weekday"] = (cast(func.strftime("%w", r.date), Integer) + 6) % 7
    if domain != "daily_ledger":
        columns.update({key: getattr(i, key) for key in ("category_id", "category_name", "include_in_total", "amount")})
    return columns


def filter_metadata(store, domain):
    metadata = {**fields_for(store, "daily_ledger"), "weekday": ["integer", None, "0=周一..6=周日"]}
    if domain in ("income_items", "income_composition"):
        metadata.update({key: info for key, info in ITEM_FIELDS.items()
                         if domain == "income_items" or key != "amount"})
    return metadata


def conditions_for(store, target, columns, metadata, start, end):
    conditions = [StoreDailyRecord.store_id == store.id,
                  StoreDailyRecord.date >= start, StoreDailyRecord.date <= end]
    for item in target.filters:
        condition = apply_filter(item, columns, metadata)
        if target.domain != "income_composition" or item.field not in ("category_id", "category_name", "include_in_total"):
            conditions.append(condition)
    return conditions


def validate_value(field, value, info):
    kind = info[0].rstrip("?")
    if kind == "integer" and type(value) is not int:
        raise ValueError("Expected integer")
    if kind == "boolean" and type(value) is not bool:
        raise ValueError("Expected boolean")
    if kind in ("string", "date") and not isinstance(value, str):
        raise ValueError("Expected text")
    if kind == "date":
        from datetime import date
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Expected YYYY-MM-DD")
        return date.fromisoformat(value)
    if field == "is_open" and value not in ("营业", "提前休息", "休息", "未统计"):
        raise ValueError("Unknown operating state")
    if field == "weekday" and not 0 <= value <= 6:
        raise ValueError("Weekday requires 0..6")
    return value


def apply_filter(item, columns, metadata):
    column, info = columns[item.field], metadata[item.field]
    if item.op in ("is_null", "not_null"):
        if item.value is not None or not info[0].endswith("?"):
            raise ValueError("Null operations only on nullable fields, without value")
        return column.is_(None) if item.op == "is_null" else column.is_not(None)
    if item.op == "in":
        if not isinstance(item.value, list) or not 1 <= len(item.value) <= 50:
            raise ValueError("Collection requires 1-50 values")
        return column.in_([validate_value(item.field, v, info) for v in item.value])
    value = validate_value(item.field, item.value, info)
    if item.op == "contains":
        if info[0].rstrip("?") != "string" or not 1 <= len(value) <= 200:
            raise ValueError("Keyword requires 1-200 text characters")
        return column.contains(value, autoescape=True)
    if item.op in ("gte", "lte"):
        if info[0].rstrip("?") not in ("integer", "date"):
            raise ValueError("Bounds only on date/number fields")
        return column >= value if item.op == "gte" else column <= value
    return column == value


def failure_receipt_capacity(targets, size=serialized_size):
    return sum(250 + size(target["id"]) for target in targets)


def following_target_capacity(targets, store, size=serialized_size):
    """Leave room for a small valid neighbor as well as invalid-target receipts."""
    capacity = 0
    for raw in targets:
        try:
            target = QueryTarget.model_validate(raw)
            if not set(target.fields).issubset(fields_for(store, target.domain)):
                raise ValueError("Unknown field")
            capacity += 1500 + size(raw)
        except ValueError:
            capacity += 250 + size(raw["id"])
    return capacity


async def execute_target(session, context, store, target):
    metadata = fields_for(store, target.domain)
    filters = filter_metadata(store, target.domain)
    if not set(target.fields).issubset(metadata) or not {f.field for f in target.filters}.issubset(filters):
        raise ValueError("Unknown or disabled catalog field")
    ordering_fields = set(target.fields) if target.fields else set(target.metrics) | set(target.group_by)
    if not {o.field for o in target.order_by}.issubset(ordering_fields):
        raise ValueError("Ordering must use selected fields, metrics or dimensions")
    columns = field_columns(target.domain)
    # Validate every predicate before any domain reads.
    for item in target.filters:
        apply_filter(item, columns, filters)
    history_domain = ("daily_ledger" if target.domain == "monthly_income" and
                      not set(target.metrics) & {"confirmed_settlement_income", "total_income", "monthly_average_income"}
                      else target.domain)
    if target.domain == "income_composition":
        from app.agents.tools.query_income import composition_dependencies
        if not composition_dependencies(target)["settlements"]:
            history_domain = "daily_ledger"
    selections = [target.range, target.compare.range if target.compare else None]
    needs_history = any(selection and (selection.all_history or (selection.base or {}).get("all_history"))
                        for selection in selections)
    history = (await date_snapshot(session, store.id, history_domain) if needs_history
               else {"start": None, "end": None})
    dates = resolve_range(target.range, local_today(store), history)
    result = {"id": target.id, "status": "complete", "domain": target.domain, **dates,
              "queried_at": datetime.now(ZoneInfo(store.timezone)).isoformat(),
              "fields": {key: metadata[key] for key in target.fields}, "metrics": {},
              "matched_count": 0, "selected_count": 0, "rows": [], "has_more": False,
              "next_cursor": None, "result_ref": None,
              "group_by": target.group_by, "statistics_scope": "all_matching",
              "definitions": "已统计=营业/提前休息/休息；未统计数值为空。台账及分类明细不含结算；月度收入按开票月计整笔已确认结算，不分摊日周；其他数据不等于成本/利润。"}
    if dates["range"] is None:
        result["status"] = "unavailable"
        result["reason"] = "no_valid_dates"
        return result
    from datetime import date
    start, end = (date.fromisoformat(dates["range"][key]) for key in ("start", "end"))
    conditions = conditions_for(store, target, columns, filters, start, end)
    if target.metrics:
        aggregate = await aggregate_target(session, store, target, start, end, conditions)
        result["notes"].extend(aggregate.pop("notes", []))
        result.update(aggregate)
        result["metric_metadata"] = {key: METRICS[target.domain][key] for key in target.metrics}
        result["selected_count"] = min(result["matched_count"], target.top_n) if target.top_n else result["matched_count"]
        select_rows(result, target)
        if target.compare:
            previous_dates = comparison_range(target.range, target.compare, local_today(store), dates["range"], history)
            if previous_dates["range"] is None:
                result["comparison"] = {**previous_dates, "status": "no_valid_dates"}
            else:
                previous_start = date.fromisoformat(previous_dates["range"]["start"])
                previous_end = date.fromisoformat(previous_dates["range"]["end"])
                previous_conditions = conditions_for(store, target, columns, filters, previous_start, previous_end)
                previous = await aggregate_target(session, store, target, previous_start, previous_end, previous_conditions)
                select_rows(previous, target)
                previous["notes"] = [*previous_dates["notes"], *previous.get("notes", [])]
                result["comparison"] = {**previous_dates, **previous,
                                        "changes": metric_changes(result, previous, target)}
        result["page_range"] = {"start": 1 if result["rows"] else 0, "end": len(result["rows"])}
        return result
    base = select(*[columns[field].label(field) for field in target.fields]).select_from(StoreDailyRecord)
    count = select(func.count()).select_from(StoreDailyRecord)
    if target.domain == "income_items":
        base = base.join(DailyIncomeItem, DailyIncomeItem.record_id == StoreDailyRecord.id)
        count = count.join(DailyIncomeItem, DailyIncomeItem.record_id == StoreDailyRecord.id)
    result["matched_count"] = await session.scalar(count.where(*conditions))
    result["selected_count"] = min(result["matched_count"], target.top_n) if target.top_n else result["matched_count"]
    ordering = []
    for order in target.order_by:
        column = columns[order.field]
        ordering.append(column.is_(None).asc())  # Unknown always comes last, for both directions.
        ordering.append(column.desc() if order.direction == "desc" else column.asc())
    ordering.extend([StoreDailyRecord.date.asc(), StoreDailyRecord.id.asc()])
    if target.domain == "income_items":
        ordering.extend([DailyIncomeItem.category_id.asc(), DailyIncomeItem.id.asc()])
    statement = base.where(*conditions).order_by(*ordering)
    if target.top_n:
        statement = statement.limit(target.top_n)
    materialized_bytes = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    stream = await session.stream(statement)
    try:
        async for row in stream.mappings():
            values = {key: value.isoformat() if hasattr(value, "isoformat") else value for key, value in row.items()}
            required = serialized_size(values) + serialized_size({**result, "rows": []})
            if required > 12000:
                raise QueryError("row_too_large", "单完整行超过工具硬容量，未截断字段或事件。",
                                 required_chars=required, matched_count=result["matched_count"],
                                 selected_count=result["selected_count"])
            materialized_bytes += len(json.dumps(values, ensure_ascii=False).encode("utf-8")) + 2
            if materialized_bytes > 4 * 1024 * 1024:
                raise QueryError("result_capacity_exceeded", "完整物化超过本轮4 MiB容量；未保留部分快照。",
                                 matched_count=result["matched_count"], selected_count=result["selected_count"], range=dates["range"])
            result["rows"].append(values)
    finally:
        await stream.close()
    result["page_range"] = {"start": 1 if result["rows"] else 0, "end": len(result["rows"])}
    return result


async def aggregate_target(session, store, target, start, end, conditions):
    if target.domain in ("monthly_income", "income_composition"):
        from app.agents.tools.query_income import aggregate_income
        result = await aggregate_income(session, store, target, start, end, conditions)
    elif target.domain == "income_items":
        from app.agents.tools.query_categories import aggregate_categories
        result = await aggregate_categories(session, store, target, start, end, conditions)
    else:
        records = await load_ledger(session, conditions, target.metrics,
                                    [name for name in target.group_by if name == "weather"],
                                    wash_count_enabled=store.wash_count_enabled)
        rows = ledger_groups(records, target, store, start, end)
        result = {**ledger_summary(records, target.metrics, store, start, end),
                  "rows": rows, "source_count": len(records),
                  "matched_count": len(rows) if target.group_by else len(records)}
    result["selected_count"] = min(result["matched_count"], target.top_n) if target.top_n else result["matched_count"]
    if target.filters:
        # A filtered-out record is still recorded. Count the range independently;
        # filter-specific quantities continue to describe only matching dates.
        record_days = await session.scalar(select(func.count()).select_from(StoreDailyRecord).where(
            StoreDailyRecord.store_id == store.id, StoreDailyRecord.date.between(start, end)))
        coverage = result["coverage"]
        coverage["interval_days"] = (end - start).days + 1
        coverage["excluded_record_days"] = record_days - coverage["record_days"]
        coverage["missing_record_days"] = coverage["interval_days"] - record_days
        coverage["scope"] = "matching_records; missing_record_days covers the unfiltered date range"
        for row in result["rows"]:
            if "coverage" in row:
                row["coverage"]["scope"] = "matching_group"
                row["coverage"]["missing_record_days"] = None
    return result


def metric_changes(current, previous, target):
    changes = {}
    for name in target.metrics:
        a, b = current["metrics"][name], previous["metrics"][name]
        current_status, previous_status = current["metric_status"][name], previous["metric_status"][name]
        difference = a - b if a is not None and b is not None and current_status == previous_status == "available" else None
        if isinstance(difference, float):
            from decimal import Decimal
            difference = float(Decimal(str(a)) - Decimal(str(b)))
        if previous_status != "available":
            status = "no_previous_records" if previous_status in ("no_statistical_ledger", "no_statistical_items") else previous_status
        elif current_status != "available":
            status = "no_current_records" if current_status in ("no_statistical_ledger", "no_statistical_items") else current_status
        elif b == 0:
            status = "zero_previous"
        else:
            status = "comparable"
        changes[name] = {"difference": difference,
                         "change_percent": rounded_percent(difference, b) if status == "comparable" else None,
                         "status": status, "unit": METRICS[target.domain][name][0], "denominator": b}
    return changes


def select_rows(result, target):
    rows = result["rows"]
    for order in reversed(target.order_by):
        def value(row):
            return row.get("metrics", {}).get(order.field, row.get(order.field))
        known = [row for row in rows if value(row) is not None]
        unknown = [row for row in rows if value(row) is None]
        rows = sorted(known, key=value, reverse=order.direction == "desc") + unknown
    if target.top_n:
        rows = rows[:target.top_n]
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
    result["rows"] = rows


async def store_query(session, context, arguments):
    continuations = bool(arguments.continuations)
    requests = arguments.continuations if continuations else arguments.targets
    response = {"status": "complete", "targets": []}
    if not continuations:
        # SQLite's legacy SELECT mode otherwise starts no physical read transaction.
        # A short read snapshot covers counts, rows, summaries and all batch targets.
        await session.execute(text("BEGIN"))
        store = await session.get(Store, context.scope.store_id, populate_existing=True)
        current_version = version(store)
        if arguments.catalog_version != current_version:
            return {"error": "catalog_stale", "catalog_version": current_version,
                    "message": "能力配置已变化；整批未执行，请刷新目录后重试。"}
        response["catalog_version"] = current_version
    # Reserve complete failure receipts for every id before any target reads.
    # At low remaining budgets even six small error messages may not fit.
    receipt_targets = [{"id": request.result_ref} if continuations else request for request in requests]
    minimum_receipts = 300 + failure_receipt_capacity(receipt_targets)
    context_capacity = context.remaining_context_chars
    if (context.remaining_result_chars < max(1000, minimum_receipts)
            or (context_capacity is not None
                and context_capacity < 300 + failure_receipt_capacity(receipt_targets, message_size))):
        if continuations:
            for request in requests:
                found = context.results.lookup_cursor(request.result_ref, request.cursor)
                if found:
                    snapshot, offset = found
                    response["targets"].append(capacity_receipt(snapshot, request.result_ref, offset, context.results))
                else:
                    response["targets"].append({"id": request.result_ref,
                                               "status": "failed", "error": "invalid_result_reference",
                                               "message": "结果引用或游标无效。"})
            response["status"] = "partial" if any(t.get("result_ref") for t in response["targets"]) else "failed"
            return response
        return {"error": "context_capacity", "message": "结果元数据及完整行空间不足，整批未执行。"}
    for index, raw in enumerate(requests):
        reference, snapshot, offset, end = None, None, 0, 0
        try:
            reserve = (failure_receipt_capacity(receipt_targets[index + 1:]) if continuations else
                       following_target_capacity(requests[index + 1:], store))
            reserve_context = (failure_receipt_capacity(receipt_targets[index + 1:], message_size) if continuations else
                               following_target_capacity(requests[index + 1:], store, message_size))
            overhead = serialized_size(response) + reserve + 152
            available = min(12000, context.remaining_result_chars) - overhead
            available_context = (context_capacity - message_size(response)
                                 - reserve_context - 154
                                 if context_capacity is not None else None)
            if continuations:
                found = context.results.lookup_cursor(raw.result_ref, raw.cursor)
                if not found:
                    raise QueryError("invalid_result_reference", "结果引用或游标无效、已结束或不属于本轮授权范围。")
                snapshot, offset = found
                reference, page_size = raw.result_ref, raw.page_size
            else:
                target = QueryTarget.model_validate(raw)
                if available < 700 or (available_context is not None and available_context < 700):
                    raise QueryError("context_capacity", "完整目标元数据及单行空间不足，当前目标未查询。")
                snapshot = await execute_target(session, context, store, target)
                reference, failure = materialize(snapshot, context.results, target.model_dump(mode="json"))
                if failure:
                    response["targets"].append(failure)
                    continue
                page_size = target.page_size
            result, end = page(snapshot, reference, offset, page_size, context.results,
                               available, available_context)
        except (ValidationError, ValueError, OverflowError) as exc:
            target_id = snapshot["id"] if snapshot else raw.result_ref if continuations else raw["id"]
            if isinstance(exc, QueryError):
                result = {"id": target_id, "status": "failed", "error": exc.code,
                          "message": exc.message, **exc.metadata}
            else:
                result = {"id": target_id, "status": "failed", "error": "invalid_query_target",
                          "message": "字段、筛选、范围或参数组合不符合已上线目录。"}
        candidate = {**response, "targets": [*response["targets"], result]}
        exceeds_context = context_capacity is not None and message_size(candidate) > context_capacity
        if serialized_size(candidate) > min(12000, context.remaining_result_chars) or exceeds_context:
            if reference:
                result = capacity_receipt(snapshot, reference, offset, context.results)
                end = offset
            else:
                result = {"id": result["id"], "status": "failed", "error": "context_capacity",
                          "message": "整个批量剩余容量不足，未截断当前目标。"}
        response["targets"].append(result)
        if reference and end > offset:
            context.results.record_read(reference, offset, end)
    completed = sum(r["status"] in ("complete", "unavailable") for r in response["targets"])
    succeeded = sum(r["status"] in ("complete", "unavailable", "partial") for r in response["targets"])
    response["status"] = "complete" if completed == len(response["targets"]) else "partial" if succeeded else "failed"
    if response["status"] == "partial":
        response["message"] = "查询部分完成；已读页保留，未读范围见各目标，续页受本轮剩余容量限制。"
    return response
