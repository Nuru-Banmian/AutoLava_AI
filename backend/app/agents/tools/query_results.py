"""Complete-row projections of immutable run-local query snapshots."""
import json

from app.agents.tools.context import ResultCapacityError


def serialized_size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False))


def message_size(value):
    # Tool JSON is a string inside the provider messages: count its second escaping.
    return len(json.dumps(json.dumps(value, ensure_ascii=False, allow_nan=False),
                          ensure_ascii=False)) - 2


def row_count(snapshot):
    return max(len(snapshot["rows"]), len(snapshot.get("comparison", {}).get("rows", [])))


def metadata(snapshot):
    result = {key: value for key, value in snapshot.items() if key != "rows"}
    if "comparison" in result:
        result["comparison"] = {key: value for key, value in result["comparison"].items()
                                if key != "rows"}
    return result


def progress(ranges, count, start=0, end=0):
    intervals = [(r["start"], r["end"]) for r in ranges]
    if end > start:
        intervals.append((start + 1, end))
    merged = []
    for left, right in sorted(intervals):
        if merged and left <= merged[-1]["end"] + 1:
            merged[-1]["end"] = max(right, merged[-1]["end"])
        else:
            merged.append({"start": left, "end": right})
    unread, position = [], 1
    for interval in merged:
        if position < interval["start"]:
            unread.append({"start": position, "end": interval["start"] - 1})
        position = interval["end"] + 1
    if position <= count:
        unread.append({"start": position, "end": count})
    prefix = merged[0]["end"] if merged and merged[0]["start"] == 1 else 0
    return {"read_ranges": merged, "read_range": {"start": 1 if prefix else 0, "end": prefix},
            "unread_ranges": unread,
            "unread_range": unread[0] if unread else {"start": 0, "end": 0}}


def capacity_receipt(snapshot, reference, offset, repository):
    count = row_count(snapshot)
    return {"id": snapshot["id"], "status": "partial", "error": "context_capacity",
            "message": "本轮剩余上下文不足；保留完整快照与已读页，未读明细未截断。",
            "result_ref": reference, "matched_count": snapshot["matched_count"],
            "selected_count": snapshot["selected_count"], "row_count": count,
            "page_range": {"start": 0, "end": 0}, "rows": [],
            "has_more": offset < count,
            "next_cursor": repository.cursor(reference, offset) if offset < count else None,
            **progress(repository.read_ranges(reference), count)}


def row_projection(snapshot, reference, offset, stop, ranges, next_cursor):
    """One shape for both the hard-limit probe and a real complete-row page."""
    count = row_count(snapshot)
    result = {**metadata(snapshot), "result_ref": reference, "row_count": count,
              "rows": snapshot["rows"][offset:stop],
              "page_range": {"start": offset + 1 if stop > offset else 0,
                             "end": stop if stop > offset else 0},
              "has_more": stop < count, "next_cursor": next_cursor,
              **progress(ranges, count, offset, stop)}
    if "comparison" in result:
        rows = snapshot["comparison"].get("rows", [])
        result["page_unit"] = "ordered_row_pair; main and comparison rows share an offset"
        result["comparison"] = {**result["comparison"], "rows": rows[offset:stop],
            "page_range": {"start": offset + 1 if offset < min(stop, len(rows)) else 0,
                           "end": min(stop, len(rows)) if offset < min(stop, len(rows)) else 0}}
    if result["unread_ranges"]:
        result["status"] = "partial"
    return result


def materialize(snapshot, repository, query_description):
    snapshot["query_description"] = query_description
    # A single complete logical row includes both sides when comparing groups.
    # Metadata/fields are never silently removed to fit the hard page ceiling.
    base = metadata(snapshot)
    for index in range(row_count(snapshot)):
        cursor = ("v1." + format(index + 1, "x") + "." + "0" * 64
                  if index + 1 < row_count(snapshot) else None)
        probe = row_projection(snapshot, "0" * 32, index, index + 1, [], cursor)
        required = serialized_size({"status": "partial", "catalog_version": "0" * 64,
                                    "targets": [probe], "message": "查询部分完成；已读页保留，未读范围见各目标，续页受本轮剩余容量限制。"})
        if required > 12000:
            return None, {"id": snapshot["id"], "status": "failed", "error": "row_too_large",
                          "message": "单完整行及必要元数据超过12000字符硬上限，未截断字段或事件。",
                          "required_chars": required, "matched_count": snapshot["matched_count"],
                          "selected_count": snapshot["selected_count"]}
    try:
        return repository.put(snapshot), None
    except ResultCapacityError:
        return None, {"id": snapshot["id"], "status": "failed", "error": "result_capacity_exceeded",
                      "message": "本轮完整快照总容量超过4 MiB，保留其他已成功目标。",
                      **{key: value for key, value in base.items() if key in (
                          "matched_count", "selected_count", "metrics", "metric_status", "coverage",
                          "statistics_scope", "range", "queried_at")}}


def page(snapshot, reference, offset, page_size, repository, char_budget, context_budget):
    count = row_count(snapshot)
    receipt = capacity_receipt(snapshot, reference, offset, repository)
    end = offset

    def projection(stop):
        cursor = repository.cursor(reference, stop) if stop < count else None
        return row_projection(snapshot, reference, offset, stop, repository.read_ranges(reference), cursor)

    def fits(result):
        return (serialized_size(result) <= char_budget
                and (context_budget is None or message_size(result) <= context_budget))

    candidate = projection(offset)
    if not fits(candidate):
        return receipt, offset
    for stop in range(offset + 1, min(count, offset + page_size) + 1):
        proposed = projection(stop)
        if not fits(proposed):
            break
        candidate, end = proposed, stop
    if count > offset and end == offset:
        return receipt, offset
    return candidate, end
