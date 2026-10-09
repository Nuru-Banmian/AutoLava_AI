"""Run-local complete-row pagination through authenticated chat and migrated SQLite."""
import json

from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_store_query import QueryModel, query
from tests.api.test_agent_tools import ask


def latest_batch(model):
    return next(value for value in reversed(model.results) if "targets" in value)


def continue_pages(model):
    return "store_query", {"continuations": [
        {"result_ref": target["result_ref"], "cursor": target["next_cursor"], "page_size": 2}
        for target in latest_batch(model)["targets"] if target.get("has_more")
    ]}


async def save_event(client, day, amount, event):
    old = await client.get(f"/api/ledger/1/{day}")
    data = old.json() if old.status_code == 200 else {}
    response = await client.put(f"/api/ledger/1/{day}", json={
        "expected_identity": data.get("identity"), "expected_revision": data.get("revision"),
        "expected_config_revision": 1, "is_open": "营业", "daily_revenue": amount,
        "activity": event,
    })
    assert response.status_code in (200, 201), response.text


async def test_long_events_paginate_immutable_batch_after_concurrent_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")
    pages = []
    class ConcurrentModel(QueryModel):
        async def stream_tools(self, messages, tools):
            batches = [json.loads(m["content"]) for m in messages if m["role"] == "tool"
                       and "targets" in json.loads(m["content"])]
            if len(batches) == 1 and not pages:
                pages.append(batches[0])
                await save_event(self.client, "2026-07-03", 999, "别人已改动事件")
                row = (await self.client.get("/api/ledger/1/2026-07-04")).json()
                deleted = await self.client.request("DELETE", "/api/ledger/1/2026-07-04", json={
                    "expected_identity": row["identity"], "expected_revision": row["revision"],
                })
                assert deleted.status_code == 204, deleted.text
                await save_event(self.client, "2026-07-06", 777, "新插入行")
            async for chunk in super().stream_tools(messages, tools):
                yield chunk
    model = ConcurrentModel([("store_data_catalog", {}), query([
        {"id": "events", "domain": "daily_ledger", "range": {"all_history": True},
         "fields": ["date", "daily_revenue", "activity"], "page_size": 2},
        {"id": "dates", "domain": "daily_ledger", "range": {"all_history": True},
         "fields": ["date"], "page_size": 2},
    ]), continue_pages, continue_pages, "已读取同次查询的全部五行。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        model.client = client
        event = "清点完整事件\n\"未截断\"。" * 70
        for day in range(1, 6):
            await save_event(client, f"2026-07-{day:02}", day * 10, event)
        run = await ask(client, "读取全部历史事件")
        assert run["status"] == "completed", run
        batches = [r for r in model.results if "targets" in r]
        assert len(batches) == 3
        for index, name in enumerate(("events", "dates")):
            targets = [batch["targets"][index] for batch in batches]
            assert all(t["id"] == name and t["matched_count"] == t["selected_count"] == 5 for t in targets)
            assert len({t["result_ref"] for t in targets}) == 1
            assert [t["page_range"] for t in targets] == [
                {"start": 1, "end": 2}, {"start": 3, "end": 4}, {"start": 5, "end": 5}]
            assert targets[-1]["read_range"] == {"start": 1, "end": 5}
            assert targets[-1]["has_more"] is False and targets[-1]["next_cursor"] is None
            rows = [row for target in targets for row in target["rows"]]
            assert [row["date"] for row in rows] == [f"2026-07-{day:02}" for day in range(1, 6)]
            if name == "events":
                assert [row["daily_revenue"] for row in rows] == [10, 20, 30, 40, 50]
                assert all(row["activity"] == event for row in rows)
        assert all(len(json.dumps(batch, ensure_ascii=False)) <= 12000 for batch in batches)
        sse = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert sse.count('"name": "store_query"') == 3
        assert "event: completed" in sse


async def test_grouped_top_n_pages_keep_all_matching_totals(tmp_path):
    from tests.api.test_agent_tools import save_day
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "rank", "domain": "daily_ledger", "range": {"start": "2026-07-01", "end": "2026-07-06"},
        "metrics": ["total_revenue"], "group_by": ["day"],
        "order_by": [{"field": "total_revenue", "direction": "desc"}],
        "top_n": 3, "page_size": 2,
    }]), continue_pages, "完整匹配合计210，选中前三天，全部选中行已读完。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        for day in range(1, 7):
            await save_day(client, f"2026-07-{day:02}", day * 10)
        run = await ask(client, "历史营业额最高三天")
        assert run["status"] == "completed", run
        pages = [r["targets"][0] for r in model.results if "targets" in r]
        assert len(pages) == 2
        assert all(p["metrics"]["total_revenue"] == 210 for p in pages)
        assert all(p["matched_count"] == 6 and p["selected_count"] == 3 for p in pages)
        assert pages[0]["page_range"] == {"start": 1, "end": 2}
        assert pages[1]["page_range"] == {"start": 3, "end": 3}
        rows = [r for p in pages for r in p["rows"]]
        assert [r["day"] for r in rows] == ["2026-07-06", "2026-07-05", "2026-07-04"]
        assert [r["rank"] for r in rows] == [1, 2, 3]
        assert "仅部分完成" not in run["output"]


async def test_comparison_pages_preserve_both_complete_snapshots(tmp_path, monkeypatch):
    from tests.api.test_agent_tools import save_day
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "compare", "domain": "daily_ledger",
        "range": {"start": "2026-07-01", "end": "2026-07-02"},
        "metrics": ["total_revenue"], "group_by": ["day"], "page_size": 2,
        "compare": {"range": {"start": "2026-06-01", "end": "2026-06-05"}},
    }]), continue_pages, continue_pages, "两期分组与全部匹配统计均已读取。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        for day in range(1, 3):
            await save_day(client, f"2026-07-{day:02}", 100)
        for day in range(1, 6):
            await save_day(client, f"2026-06-{day:02}", 20)
        run = await ask(client, "比较两期全部逐日统计")
        assert run["status"] == "completed", run
        pages = [r["targets"][0] for r in model.results if "targets" in r]
        assert len(pages) == 3
        assert all(p["selected_count"] == 2 and p["row_count"] == 5 for p in pages)
        assert all(p["metrics"]["total_revenue"] == 200 for p in pages)
        assert all(p["comparison"]["metrics"]["total_revenue"] == 100 for p in pages)
        assert [r["day"] for p in pages for r in p["rows"]] == ["2026-07-01", "2026-07-02"]
        assert [r["day"] for p in pages for r in p["comparison"]["rows"]] == [
            f"2026-06-{day:02}" for day in range(1, 6)]
        assert pages[-1]["read_range"] == {"start": 1, "end": 5}
        assert pages[-1]["has_more"] is False
        assert "仅部分完成" not in run["output"]
