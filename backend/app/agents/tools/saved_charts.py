"""Authorized, paginated saved drawing evidence; never reads business tables."""
from sqlalchemy import select

from app.models.agent import AgentChart, AgentConversation, AgentMessage
from app.agents.tools.query_results import materialize, page, serialized_size, message_size


async def authorized_chart(session, scope, message_id, chart_id):
    return await session.scalar(select(AgentChart).join(AgentMessage).join(AgentConversation).where(
        AgentChart.chart_id == chart_id, AgentChart.message_id == message_id,
        AgentMessage.role == "assistant", AgentConversation.user_id == scope.user_id,
        AgentConversation.store_id == scope.store_id,
    ))


async def read_saved(session, context, args):
    response = {"source": "saved_chart", "status": "complete", "targets": []}
    reference, offset = args.result_ref, 0
    if reference:
        found = context.results.lookup_cursor(reference, args.cursor)
        if not found or found[0].get("source") != "saved_chart":
            return {"error": "invalid_result_reference", "message": "历史图引用或游标不属于本轮有效选择。"}
        snapshot, offset = found
        message_id, chart_id = snapshot["message_id"], snapshot["chart_id"]
    else:
        message_id, chart_id = args.message_id, args.chart_id
    # Continuations also recheck the saved chart's current message association.
    chart = await authorized_chart(session, context.scope, message_id, chart_id)
    if chart is None:
        return {"error": "saved_chart_not_found", "message": "历史图不存在或不在当前授权消息范围。"}
    if not reference:
        payload = chart.payload
        selected = args.series or [s["key"] for s in payload["series"]]
        end = args.point_end if args.point_end is not None else len(payload["points"])
        if (not set(selected) <= {s["key"] for s in payload["series"]}
                or not 1 <= args.point_start <= end <= len(payload["points"])):
            return {"error": "invalid_chart_selection", "message": "历史图系列或点范围无效。"}
        rows = [{**p, "values": {key: p["values"][key] for key in selected}}
                for p in payload["points"][args.point_start - 1:end]]
        drawing = {key: value for key, value in payload.items() if key != "points"}
        drawing["series"] = [s for s in payload["series"] if s["key"] in selected]
        snapshot = {"id": chart_id, "status": "complete", "source": "saved_chart",
            "message_id": message_id, "chart_id": chart_id, "queried_at": payload["queried_at"],
            "range": payload["range"], "matched_count": len(payload["points"]),
            "selected_count": len(rows), "selection": {"point_start": args.point_start, "point_end": end},
            "statistics_scope": "selected_saved_chart_points; coverage describes original query",
            "drawing": drawing, "rows": rows}
        reference, failure = materialize(snapshot, context.results, {
            "source": "saved_chart", "message_id": message_id, "chart_id": chart_id,
            "series": selected, "point_start": args.point_start, "point_end": end,
        })
        if failure:
            return {**response, "status": "failed", "targets": [failure]}
    available = min(12000, context.remaining_result_chars) - serialized_size(response) - 250
    available_context = (None if context.remaining_context_chars is None
                         else context.remaining_context_chars - message_size(response) - 250)
    result, stop = page(snapshot, reference, offset, args.page_size, context.results,
                        available, available_context)
    result.update(source="saved_chart", queried_at=snapshot["queried_at"])
    if stop > offset:
        context.results.record_read(reference, offset, stop)
    return {**response, "status": result["status"], "targets": [result],
            "message": "依据已保存图表及原查询时间；未读点不得冒称读全。"}


def project_saved(snapshot, args):
    from app.agents.tools.store_chart import segment_drafts, period_end
    drawing = snapshot["drawing"]
    keys = {s["key"] for s in drawing["series"]}
    time_axis = drawing["dimension"] in ("day", "week", "month", "year")
    if (args.block != "main" or args.dimension != drawing["dimension"] or args.series_by is not None
            or not set(args.series) <= keys or len(set(args.series)) != len(args.series)
            or (args.type == "line" and not time_axis)
            or (args.type == "horizontal_bar" and drawing["type"] != "horizontal_bar")
            or (args.type == "stacked_bar" and drawing["type"] != "stacked_bar")):
        raise ValueError("invalid_chart_source")
    payload = {**drawing, "title": args.title, "type": args.type,
               "series": [s for s in drawing["series"] if s["key"] in args.series],
               "points": [{**p, "values": {key: p["values"][key] for key in args.series}}
                          for p in snapshot["rows"]],
               "notes": [*drawing["notes"], "依据保存图快照再次绘制；查询时间与覆盖沿用原图，点范围见来源选择。"]}
    if time_axis and snapshot["selected_count"] < snapshot["matched_count"]:
        first = str(payload["points"][0]["dimension"])
        first += "-01" if args.dimension == "month" else "-01-01" if args.dimension == "year" else ""
        payload["range"] = {"start": max(first, drawing["range"]["start"]),
                            "end": min(period_end(str(payload["points"][-1]["dimension"]), args.dimension), drawing["range"]["end"])}
        # The original segment metadata belongs to the source, not a newly selected slice.
        payload.pop("segment", None)
    return segment_drafts(payload, {"source": "saved_chart", "message_id": snapshot["message_id"],
        "chart_id": snapshot["chart_id"], "query": snapshot["query_description"],
        "queried_at": snapshot["queried_at"], "original_range": drawing["range"],
        "statistics_scope": snapshot["statistics_scope"]})
