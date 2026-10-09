"""Project immutable query results into bounded, run-local chart drafts."""
import json
import math
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.agents.tools.query_definitions import METRICS


class ChartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["create"]
    result_ref: str = Field(min_length=32, max_length=32)
    block: Literal["main", "comparison"] = "main"
    dimension: Literal["day", "week", "month", "year"]
    series: list[str] = Field(min_length=1, max_length=6)
    type: Literal["line"]
    title: str = Field(min_length=1, max_length=80)


def byte_size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def descriptor(draft):
    payload = draft["payload"]
    return {"chart_id": draft["chart_id"], "schema_version": 1, "type": payload["type"],
            "title": payload["title"], "unit": payload["unit"], "range": payload["range"],
            "point_count": len(payload["points"])}


def project(snapshot, args):
    block = snapshot if args.block == "main" else snapshot.get("comparison", {})
    if (snapshot.get("status") != "complete" or block.get("status", "complete") != "complete"
            or snapshot.get("group_by") != [args.dimension] or not block.get("rows")
            or len(set(args.series)) != len(args.series)):
        raise ValueError("invalid_chart_source")
    definitions = METRICS[snapshot["domain"]]
    if any(name not in block.get("metrics", {}) or name not in definitions for name in args.series):
        raise ValueError("invalid_chart_source")
    units = {definitions[name][0] for name in args.series}
    if len(units) != 1:
        raise ValueError("chart_mixed_units")
    if len(block["rows"]) > 366:
        raise ValueError("chart_capacity_exceeded")
    points = []
    for row in sorted(block["rows"], key=lambda row: row[args.dimension]):
        values = {}
        for name in args.series:
            raw = row.get("metrics", {}).get(name)
            status = row.get("metric_status", {}).get(name, "unknown")
            if raw is None or status != "available":
                values[name] = {"exact": None, "plot": None, "status": status}
                continue
            value = Decimal(str(raw))
            if not value.is_finite() or abs(value) > 9007199254740991:
                raise ValueError("chart_unsafe_value")
            plot = float(value)
            if not math.isfinite(plot) or Decimal(str(plot)) != value:
                raise ValueError("chart_unsafe_value")
            values[name] = {"exact": str(raw), "plot": plot, "status": status}
        points.append({"dimension": row[args.dimension], "state": row.get("state", "汇总"),
                       "values": values})
    payload = {"type": args.type, "title": args.title, "dimension": args.dimension,
               "granularity": args.dimension, "unit": units.pop(), "range": block["range"],
               "queried_at": snapshot["queried_at"], "coverage": block.get("coverage", {}),
               "unfinished": block.get("unfinished", False),
               "notes": block.get("notes", []),
               "series": [{"key": name, "label": definitions[name][1]} for name in args.series],
               "points": points}
    source = {"result_ref": args.result_ref, "target_id": snapshot["id"], "block": args.block,
              "query": snapshot["query_description"], "statistics_scope": snapshot["statistics_scope"]}
    draft = {"chart_id": uuid4().hex, "payload": payload, "source": source}
    # Account for the normalized snapshot and lightweight description together.
    # Reserve bounded persistence metadata (message/position/time/size) before publish.
    draft["byte_size"] = byte_size({**draft, "schema_version": 1, "summary": descriptor(draft)}) + 128
    if draft["byte_size"] > 96 * 1024:
        raise ValueError("chart_capacity_exceeded")
    return draft


async def store_chart(session, context, args):
    snapshot = context.results.get(args.result_ref)
    if snapshot is None:
        return {"error": "invalid_chart_source", "message": "图表来源不属于本轮有效查询。"}
    # result_ref addresses the complete immutable snapshot, never a returned page.
    # Chart projection must not force thousands of source rows into model context.
    try:
        drafts = [project(snapshot, args)]
        context.results.prepare_charts(drafts)
    except (ValueError, InvalidOperation) as exc:
        code = str(exc) if str(exc) in {"invalid_chart_source", "chart_mixed_units", "chart_unsafe_value",
                                       "chart_capacity_exceeded"} else "invalid_chart_source"
        return {"error": code, "message": "图表未生成；请检查完整来源、单位及容量。"}
    return {"status": "prepared", "charts": [descriptor(draft) for draft in drafts],
            "message": "图表已准备，随最终回答保存；请给简短分析，用户要求明细时仍提供。"}
