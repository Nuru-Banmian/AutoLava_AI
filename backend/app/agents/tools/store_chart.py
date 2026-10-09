"""Project immutable query results into bounded, run-local chart drafts."""
import json
import math
import re
from datetime import date, timedelta
from calendar import monthrange
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.agents.tools.query_definitions import METRICS


class CreateChartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["create"]
    result_ref: str = Field(min_length=32, max_length=32)
    block: Literal["main", "comparison"] = Field(default="main", description=(
        "main contains only current-period rows; comparison contains only baseline-period rows. "
        "Neither merges periods. A two-month chart requires one query spanning both months with group_by:[month]."))
    dimension: Literal["day", "week", "month", "year", "category", "weather", "weekday", "date"]
    series: list[str] = Field(min_length=1, max_length=6, description=(
        "Selected numeric metric/field keys, not display labels. Category pivot requires series:[amount] "
        "and series_by:category, never category names."))
    series_by: Literal["category"] | None = None
    type: Literal["line", "grouped_bar", "stacked_bar", "horizontal_bar"]
    title: str = Field(min_length=1, max_length=80)


class ChartInput(RootModel[CreateChartInput]):
    @classmethod
    def model_json_schema(cls, **kwargs):
        # Providers receive the same creation-only contract as runtime validation.
        schema = CreateChartInput.model_json_schema()

        def compact(value):
            if isinstance(value, list):
                return [compact(item) for item in value]
            if isinstance(value, dict):
                # Optional arguments are omitted rather than explicitly null.
                # Keep bounds and business property names while dropping the
                # redundant null branch from the provider-facing schema.
                if "anyOf" in value:
                    alternatives = [item for item in value["anyOf"] if item.get("type") != "null"]
                    if len(alternatives) == 1:
                        return compact({**alternatives[0], **{
                            key: item for key, item in value.items() if key != "anyOf"
                        }})
                return {key: ({name: compact(item) for name, item in content.items()}
                              if key == "properties" else compact(content))
                        for key, content in value.items() if key not in ("title", "default")}
            return value

        return compact(schema)


def byte_size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def descriptor(draft):
    payload = draft["payload"]
    return {"chart_id": draft["chart_id"], "schema_version": 1, "type": payload["type"],
            "title": payload["title"], "unit": payload["unit"], "range": payload["range"],
            "point_count": len(payload["points"]), "segment": payload.get("segment"),
            "queried_at": payload["queried_at"], "source": draft["source"].get("source", "store_query")}


def chart_value(raw, status):
    if raw is None or status != "available":
        return {"exact": None, "plot": None, "status": status}
    value = Decimal(str(raw))
    if not value.is_finite() or abs(value) > 9007199254740991:
        raise ValueError("chart_unsafe_value")
    plot = float(value)
    if not math.isfinite(plot) or Decimal(str(plot)) != value:
        raise ValueError("chart_unsafe_value")
    return {"exact": str(raw), "plot": plot, "status": status}


def validate_stack(snapshot, args, rows):
    if args.type != "stacked_bar":
        return
    components = {"daily_ledger_revenue", "confirmed_settlement_income"}
    valid = (snapshot["domain"] == "monthly_income" and set(args.series) == components
             and args.series_by is None)
    if args.series_by == "category" and args.series == ["amount"]:
        valid = (snapshot["domain"] in ("income_items", "income_composition")
                 and all(row.get("include_in_total") is True for row in rows)
                 and len({row.get("denominator_scope", "total_income") for row in rows}) == 1)
    if not valid:
        raise ValueError("chart_incompatible_stack")


def source_definitions(snapshot):
    if snapshot.get("fields"):
        return {key: [info[1], info[2]] for key, info in snapshot["fields"].items()
                if key in ("daily_revenue", "wash_count", "amount")}
    return METRICS[snapshot["domain"]]


def project(snapshot, args):
    block = snapshot if args.block == "main" else snapshot.get("comparison", {})
    grouping = [args.dimension, "category"] if args.series_by else [args.dimension]
    detail = bool(snapshot.get("fields"))
    if args.type == "horizontal_bar" and not snapshot["query_description"].get("top_n"):
        raise ValueError("chart_explicit_ranking_required")
    if (args.type != "horizontal_bar" and args.dimension in ("day", "week", "month", "year")
            and snapshot["query_description"].get("top_n")):
        raise ValueError("invalid_chart_source")
    if args.type == "line" and args.dimension not in ("day", "week", "month", "year"):
        raise ValueError("invalid_chart_source")
    if args.series_by and (args.dimension == "category" or args.type == "horizontal_bar"):
        raise ValueError("invalid_chart_source")
    if (snapshot.get("status") != "complete" or block.get("status", "complete") != "complete"
            or (not detail and set(snapshot.get("group_by", [])) != set(grouping)) or not block.get("rows")
            or len(set(args.series)) != len(args.series)):
        raise ValueError("invalid_chart_source")
    definitions = source_definitions(snapshot)
    if detail and (args.type != "horizontal_bar" or args.dimension != "date" or args.series_by is not None
                   or "date" not in snapshot["fields"]):
        raise ValueError("invalid_chart_source")
    if any(name not in (snapshot["fields"] if detail else block.get("metrics", {})) or name not in definitions for name in args.series):
        raise ValueError("invalid_chart_source")
    units = {definitions[name][0] for name in args.series}
    if len(units) != 1:
        raise ValueError("chart_mixed_units")
    validate_stack(snapshot, args, block["rows"])
    points = []
    rows = block["rows"] if args.type == "horizontal_bar" else sorted(block["rows"], key=lambda row: str(row[args.dimension]))
    for row in rows:
        values = {}
        for name in args.series:
            raw = row.get(name) if detail else row.get("metrics", {}).get(name)
            status = ("available" if raw is not None else "unknown") if detail else row.get("metric_status", {}).get(name, "unknown")
            values[name] = chart_value(raw, status)
        points.append({"dimension": row[args.dimension] if row[args.dimension] is not None else "未记录",
                       "state": row.get("state", row.get("is_open", "未查询营业状态" if detail else "汇总")),
                       "values": values})
    series = [{"key": name, "label": definitions[name][1]} for name in args.series]
    if args.series_by:
        points, series = category_points(snapshot, block, args, definitions)
    payload = {"type": args.type, "title": args.title, "dimension": args.dimension,
               "granularity": args.dimension, "unit": units.pop(), "range": block["range"],
               "queried_at": snapshot["queried_at"], "coverage": block.get("coverage", {}),
               "unfinished": block.get("unfinished", False),
               "notes": block.get("notes", []),
               "series": series,
               "points": points}
    source = {"result_ref": args.result_ref, "target_id": snapshot["id"], "block": args.block,
              "query": snapshot["query_description"], "statistics_scope": snapshot["statistics_scope"]}
    return segment_drafts(payload, source)


def period_end(key, dimension):
    if dimension == "year":
        return f"{key}-12-31"
    if dimension == "month":
        year, month = map(int, key.split("-"))
        return f"{key}-{monthrange(year, month)[1]:02}"
    first = date.fromisoformat(key)
    return (first + timedelta(days=6) if dimension == "week" else first).isoformat()


def segment_drafts(payload, source):
    time_axis = payload["dimension"] in ("day", "week", "month", "year") and payload["type"] != "horizontal_bar"
    limit = 366 if time_axis else 50
    points = payload["points"]
    if not time_axis and len(points) > limit:
        raise ValueError("chart_capacity_exceeded")
    count = (len(points) + limit - 1) // limit
    if count > 8:
        raise ValueError("chart_capacity_exceeded")
    plotted = [v["plot"] for p in points for v in p["values"].values() if v["plot"] is not None]
    if payload["type"] == "stacked_bar":
        plotted += [chart_value(sum((Decimal(v["exact"]) for v in p["values"].values()
                                     if v["exact"] is not None), Decimal(0)), "available")["plot"] for p in points]
    domain = [min([0, *plotted]), max([0, *plotted])]
    drafts = []
    for index in range(count):
        section = points[index * limit:(index + 1) * limit]
        drawing = {**payload, "points": section, "y_domain": domain}
        if count > 1:
            start_key = section[0]["dimension"]
            start = start_key + ("-01" if payload["dimension"] == "month" else "-01-01" if payload["dimension"] == "year" else "")
            drawing["range"] = {"start": max(start, payload["range"]["start"]),
                                "end": min(period_end(section[-1]["dimension"], payload["dimension"]), payload["range"]["end"])}
            drawing["segment"] = {"index": index + 1, "count": count, "total_range": payload["range"]}
            drawing["notes"] = [*payload["notes"], "覆盖信息基于完整查询总范围，各段使用相同纵轴。"]
        draft = {"chart_id": uuid4().hex, "payload": drawing, "source": source}
        # Includes descriptor/source and bounded persistence metadata before atomic reservation.
        draft["byte_size"] = byte_size({**draft, "schema_version": 1, "summary": descriptor(draft)}) + 128
        if draft["byte_size"] > 96 * 1024:
            raise ValueError("chart_capacity_exceeded")
        drafts.append(draft)
    return drafts


def category_points(snapshot, block, args, definitions):
    # Stable identity includes historical flags, names and synthetic source, never just a label.
    rows = block["rows"]
    identities = list(dict.fromkeys((r.get("category_id"), r.get("category_name"),
                                    r.get("include_in_total"), r.get("source")) for r in rows))
    if len(identities) * len(args.series) > 6:
        raise ValueError("chart_capacity_exceeded")
    series = [{"key": f"c{index}:{metric}", "label": f"{identity[1]} · {definitions[metric][1]}"}
              for index, identity in enumerate(identities) for metric in args.series]
    if len(args.series) == 1:
        for item, identity in zip(series, identities, strict=True):
            item["label"] = identity[1]
    grouped = defaultdict(dict)
    for row in rows:
        identity = (row.get("category_id"), row.get("category_name"), row.get("include_in_total"), row.get("source"))
        key = (row[args.dimension], identities.index(identity))
        if key[1] in grouped[key[0]]:
            raise ValueError("invalid_chart_source")
        grouped[key[0]][key[1]] = row
    dimensions = sorted(grouped)
    if args.dimension in ("month", "year") and not snapshot["query_description"].get("top_n"):
        from app.agents.tools.query_income import periods
        dimensions = [key for key, _, _ in periods(date.fromisoformat(block["range"]["start"]),
                                                  date.fromisoformat(block["range"]["end"]), args.dimension)]
    points = []
    for dimension in dimensions:
        values = {}
        for index in range(len(identities)):
            row = grouped[dimension].get(index)
            for metric in args.series:
                status = row.get("metric_status", {}).get(metric, "unknown") if row else "unknown"
                values[f"c{index}:{metric}"] = chart_value(row.get("metrics", {}).get(metric) if row else None, status)
        points.append({"dimension": dimension, "state": "汇总", "values": values})
    return points, series


async def store_chart(session, context, args):
    snapshot = context.results.get(args.result_ref)
    if snapshot is None:
        return {"error": "invalid_chart_source", "message": "图表来源不属于本轮有效查询。"}
    # Input validity alone does not prove the selected block covers the user's
    # comparison or categories. Reject misleading drafts before preparing them.
    comparison = snapshot.get("comparison", {})
    if (args.dimension == "month" and comparison
            and re.search(r"比较|对比|对照|两月|双月", context.question)
            and not re.search(r"只(?:画|绘制|显示|展示).{0,8}(?:本期|基期|上月|本月)", context.question)):
        required = {row["month"] for block in (snapshot, comparison)
                    for row in block.get("rows", []) if "month" in row}
        selected = snapshot if args.block == "main" else comparison
        actual = {row["month"] for row in selected.get("rows", []) if "month" in row}
        if required and not required.issubset(actual):
            ranges = [block["range"] for block in (snapshot, comparison) if block.get("range")]
            return {"error": "chart_periods_missing", "required_months": sorted(required),
                    "selected_months": sorted(actual),
                    "required_range": {"start": min(r["start"] for r in ranges),
                                       "end": max(r["end"] for r in ranges)},
                    "message": "双月比较图未生成：所选block只有一个时期，不能表示双方。"
                               "保留compare回执计算差额；另用store_query覆盖required_range、"
                               "相同domain/metrics及group_by:[month]，再用新result_ref画图。"
                               "不要在旧引用上切换block重试；不得宣称图已包含两个月。"}
    if (args.type == "stacked_bar" and args.series_by != "category"
            and re.search(r"现金|刷卡|分类|各类", context.question)):
        return {"error": "chart_categories_missing",
                "message": "分类构成图未生成：台账合计不能代替现金/刷卡等独立分类。"
                           "需要公司结算的月度分类构成用income_composition、metrics:[amount]、"
                           "group_by:[month,category]重新查询；store_chart用dimension:month、"
                           "series:[amount]、series_by:category、type:stacked_bar。"
                           "排除不计入总额的数据；使用新result_ref，不声称聚合台账系列已拆分类。"}
    # result_ref addresses the complete immutable snapshot, never a returned page.
    # Chart projection must not force thousands of source rows into model context.
    try:
        if snapshot.get("source") == "saved_chart":
            raise ValueError("invalid_chart_source")
        definitions = source_definitions(snapshot)
        if any(name not in definitions for name in args.series):
            raise ValueError("invalid_chart_source")
        units = dict.fromkeys(definitions[name][0] for name in args.series)
        groups = [project(snapshot, args.model_copy(update={
            "series": [name for name in args.series if definitions[name][0] == unit]
        })) for unit in units]
        drafts = [draft for group in groups for draft in group]
        context.results.prepare_charts(drafts)
    except (ValueError, InvalidOperation) as exc:
        code = str(exc) if str(exc) in {"invalid_chart_source", "chart_mixed_units", "chart_unsafe_value", "chart_incompatible_stack", "chart_explicit_ranking_required",
                                       "chart_capacity_exceeded"} else "invalid_chart_source"
        return {"error": code, "message": "图表未生成；来源须完整，group_by与dimension一致且有分组行。"
                                          "月度图用一个完整日期范围目标和group_by:[month]；"
                                          "分类月度堆叠用[month,category]、series:[amount]及series_by:category，series不传分类名。"
                                          "无分组汇总不能直接画图，请修正查询/图表参数后重试；核对单位和容量。"}
    return {"status": "prepared", "charts": [descriptor(draft) for draft in drafts],
            "message": "图表已从完整快照准备，随最终回答保存；point_count为图中全部点数，与模型已读明细页数分别说明。"
                       "请给简短分析，用户要求明细时仍提供。"}
