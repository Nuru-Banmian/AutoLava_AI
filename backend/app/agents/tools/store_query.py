"""Read-only projected queries; no ORM business object or settlement loading."""
import json
from dataclasses import replace
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select

from app.agents.tools.query_dates import DateRange, resolve_range
from app.agents.tools.store_catalog import date_snapshot, fields_for, local_today, version
from app.models.identity import Store
from app.models.ledger import DailyIncomeItem, StoreDailyRecord


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QueryInput(StrictInput):
    catalog_version: str = Field(min_length=1, max_length=64)
    targets: list[dict[str, Any]] = Field(min_length=1, max_length=6, description=(
        "Unique id, domain daily_ledger/income_items, fields (1-16), range: start/end OR preset"
        "(+n for last_n_*; +base for same_period_last_year) OR all_history:true. Omit range=month to date. "
        "Optional filters:[{field,op,value}], order_by:[{field,direction:asc/desc}], top_n:1-100. "
        "Only catalog fields; no metrics/group_by/compare/page_size until those capabilities ship."))

    @model_validator(mode="after")
    def unique_ids(self):
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


class QueryTarget(StrictInput):
    id: str = Field(min_length=1, max_length=64)
    domain: Literal["daily_ledger", "income_items"]
    range: DateRange | None = None
    fields: list[str] = Field(min_length=1, max_length=16)
    metrics: list[str] = Field(default_factory=list, max_length=16)
    group_by: list[str] = Field(default_factory=list, max_length=2)
    filters: list[Filter] = Field(default_factory=list, max_length=8)
    order_by: list[Order] = Field(default_factory=list, max_length=2)
    top_n: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def supported(self):
        if self.metrics or self.group_by:
            raise ValueError("Metrics and grouping are not in the published catalog yet")
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
    if domain == "daily_ledger":
        return {key: getattr(r, key) for key in ("date", "is_open", "daily_revenue", "wash_count", "weather", "activity")}
    return {"date": r.date, **{key: getattr(i, key) for key in
                              ("category_id", "category_name", "include_in_total", "amount")}}


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


def serialized_size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False))


async def execute_target(session, context, store, target, hard_capacity):
    metadata = fields_for(store, target.domain)
    requested = set(target.fields) | {f.field for f in target.filters} | {o.field for o in target.order_by}
    if not requested.issubset(metadata):
        raise ValueError("Unknown or disabled catalog field")
    columns = field_columns(target.domain)
    conditions = [StoreDailyRecord.store_id == store.id]
    conditions.extend(apply_filter(f, columns, metadata) for f in target.filters)
    history = await date_snapshot(session, store.id, target.domain)
    dates = resolve_range(target.range, local_today(store), history)
    result = {"id": target.id, "status": "complete", "domain": target.domain, **dates,
              "queried_at": datetime.now(ZoneInfo(store.timezone)).isoformat(),
              "fields": {key: metadata[key] for key in target.fields}, "metrics": {},
              "matched_count": 0, "selected_count": 0, "rows": [], "has_more": False,
              "next_cursor": None, "result_ref": None,
              "definitions": "已统计=营业/提前休息/休息；未统计数值为空，不解释成零。台账和分类金额不含公司结算。其他数据不解释为成本或利润。"}
    if dates["range"] is None:
        result["status"] = "unavailable"
        result["reason"] = "no_valid_dates"
        return result
    from datetime import date
    conditions.extend([StoreDailyRecord.date >= date.fromisoformat(dates["range"]["start"]),
                       StoreDailyRecord.date <= date.fromisoformat(dates["range"]["end"])])
    base = select(*[columns[field].label(field) for field in target.fields]).select_from(StoreDailyRecord)
    count = select(func.count()).select_from(StoreDailyRecord)
    if target.domain == "income_items":
        base = base.join(DailyIncomeItem, DailyIncomeItem.record_id == StoreDailyRecord.id)
        count = count.join(DailyIncomeItem, DailyIncomeItem.record_id == StoreDailyRecord.id)
    result["matched_count"] = await session.scalar(count.where(*conditions))
    result["selected_count"] = min(result["matched_count"], target.top_n) if target.top_n else result["matched_count"]
    if result["selected_count"] > 200:
        raise QueryError("result_capacity_exceeded", "分页尚未上线，结果超过200完整行；请明确缩小范围或选择top_n。",
                         matched_count=result["matched_count"], selected_count=result["selected_count"], range=dates["range"])
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
    for row in (await session.execute(statement)).mappings():
        values = {key: value.isoformat() if hasattr(value, "isoformat") else value for key, value in row.items()}
        row_size = serialized_size(values)
        if row_size + serialized_size({**result, "rows": []}) > 12000:
            raise QueryError("row_too_large", "单完整行超过工具硬容量，未截断字段或事件。", required_chars=row_size)
        result["rows"].append(values)
        if serialized_size(result) > context.remaining_result_chars:
            code = "context_capacity" if context.remaining_result_chars < hard_capacity else "result_capacity_exceeded"
            raise QueryError(code, "完整结果无法装入本轮容量；未返回截断明细。",
                             matched_count=result["matched_count"], selected_count=result["selected_count"], range=dates["range"])
    result["page_range"] = {"start": 1 if result["rows"] else 0, "end": len(result["rows"])}
    return result


async def store_query(session, context, arguments):
    store = await session.get(Store, context.scope.store_id)
    current_version = version(store)
    if arguments.catalog_version != current_version:
        return {"error": "catalog_stale", "catalog_version": current_version,
                "message": "能力配置已变化；整批未执行，请刷新目录后重试。"}
    response = {"status": "complete", "catalog_version": current_version, "targets": []}
    # Reserve complete failure receipts for every id before any target reads.
    # At low remaining budgets even six small error messages may not fit.
    minimum_receipts = 300 + sum(250 + serialized_size(target["id"]) for target in arguments.targets)
    if context.remaining_result_chars < max(1000, minimum_receipts):
        return {"error": "context_capacity", "message": "结果元数据及完整行空间不足，整批未执行。"}
    for index, raw in enumerate(arguments.targets):
        try:
            target = QueryTarget.model_validate(raw)
            overhead = serialized_size(response) + 250 * (len(arguments.targets) - index)
            hard_capacity = 12000 - overhead
            available = min(12000, context.remaining_result_chars) - overhead
            if available < 700:
                raise QueryError("context_capacity" if context.remaining_result_chars < 12000 else "result_capacity_exceeded",
                                 "完整目标元数据及单行空间不足，当前目标未查询。")
            result = await execute_target(session, replace(context, remaining_result_chars=available), store, target, hard_capacity)
        except (ValidationError, ValueError, OverflowError) as exc:
            if isinstance(exc, QueryError):
                result = {"id": raw["id"], "status": "failed", "error": exc.code,
                          "message": exc.message, **exc.metadata}
            else:
                result = {"id": raw["id"], "status": "failed", "error": "invalid_query_target",
                          "message": "字段、筛选、范围或参数组合不符合已上线目录。"}
        candidate = {**response, "targets": [*response["targets"], result]}
        if serialized_size(candidate) > min(12000, context.remaining_result_chars):
            result = {"id": raw["id"], "status": "failed", "error": (
                "context_capacity" if context.remaining_result_chars < 12000 else "result_capacity_exceeded"),
                      "message": "整个批量剩余容量不足，未截断当前目标。"}
        response["targets"].append(result)
    succeeded = sum(r["status"] in ("complete", "unavailable") for r in response["targets"])
    response["status"] = "complete" if succeeded == len(response["targets"]) else "partial" if succeeded else "failed"
    return response
