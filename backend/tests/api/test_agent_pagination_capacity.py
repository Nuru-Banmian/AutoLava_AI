"""Capacity acceptance via authenticated HTTP/SSE and controlled model receipts.

Large historical ledgers are fixture-seeded with the real model in migrated SQLite.
The controlled model echoes compact summaries of its public tool messages; all
acceptance assertions read the saved HTTP answer and persisted SSE events.
"""
from datetime import date, timedelta
import hashlib
import json
from uuid import uuid4

from app.models.ledger import StoreDailyRecord
from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_store_query import QueryModel, query
from tests.api.test_agent_tools import ask


EVIDENCE_MARKER = "容量证据："


async def seed_history(factory, count, event):
    """Only a fixture: legitimate past records and events within the 2000 limit."""
    first = date(2020, 1, 1)
    async with factory() as session:
        session.add_all([
            StoreDailyRecord(
                identity=str(uuid4()), revision=1, store_id=1,
                date=first + timedelta(days=index), daily_revenue=index + 1,
                income_mode="legacy_total", is_open="营业", activity=event,
                created_by=1, updated_by=1,
            )
            for index in range(count)
        ])
        await session.commit()


def echo_capacity_evidence(model):
    """Echo publicly supplied provider receipts without consulting implementation state."""
    batches = []
    for message in model.messages[-1]:
        if message["role"] != "tool":
            continue
        result = json.loads(message["content"])
        if "targets" not in result:
            continue
        targets = []
        for target in result["targets"]:
            summary = {key: target[key] for key in (
                "id", "status", "error", "required_chars", "matched_count", "selected_count",
                "result_ref", "has_more", "next_cursor", "page_range", "read_range",
            ) if key in target}
            rows = target.get("rows", [])
            summary["returned_count"] = len(rows)
            summary["dates"] = [row["date"] for row in rows if "date" in row]
            summary["activity_digests"] = [
                hashlib.sha256(row["activity"].encode("utf-8")).hexdigest()
                for row in rows if row.get("activity") is not None
            ]
            targets.append(summary)
        batches.append({"status": result["status"], "targets": targets})
    return EVIDENCE_MARKER + json.dumps({"batches": batches}, ensure_ascii=False)


def continue_target(target_id, page_size):
    def action(model):
        batch = next(result for result in reversed(model.results) if "targets" in result)
        target = next(target for target in batch["targets"] if target["id"] == target_id)
        return "store_query", {"continuations": [{
            "result_ref": target["result_ref"], "cursor": target["next_cursor"],
            "page_size": page_size,
        }]}
    return action


async def public_evidence(client, run):
    assert run["status"] == "completed", json.dumps(run, ensure_ascii=False)
    saved = await client.get(f"/api/agent/1/runs/{run['id']}")
    assert saved.status_code == 200, saved.text
    output = saved.json()["output"]
    evidence, _ = json.JSONDecoder().raw_decode(output.split(EVIDENCE_MARKER, 1)[1])
    history = await client.get("/api/agent/1/conversation")
    assert history.status_code == 200, history.text
    assert history.json()["messages"][-1]["content"] == output
    events = await client.get(f"/api/agent/1/runs/{run['id']}/events")
    assert events.status_code == 200, events.text
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "event: completed" in events.text
    assert "event: failed" not in events.text
    return evidence["batches"], output, events.text


async def test_control_character_row_too_large_preserves_small_date_target(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")
    model = QueryModel([
        ("store_data_catalog", {}),
        query([
            {"id": "event", "domain": "daily_ledger", "range": {"all_history": True},
             "fields": ["date", "activity"]},
            {"id": "dates", "domain": "daily_ledger", "range": {"all_history": True},
             "fields": ["date"]},
        ]),
        echo_capacity_evidence,
    ])
    async with chat_app(tmp_path, model) as (client, _, factory):
        await seed_history(factory, 1, "\x01" * 2000)
        batches, _, events = await public_evidence(client, await ask(client, "查询完整事件和日期"))
        batch = batches[0]
        oversized, dates = batch["targets"]
        assert batch["status"] == "partial"
        assert oversized["id"] == "event" and oversized["error"] == "row_too_large"
        assert oversized["required_chars"] > 12000
        assert oversized["returned_count"] == 0 and not oversized.get("result_ref")
        assert dates["id"] == "dates" and dates["status"] == "complete"
        assert dates["matched_count"] == dates["selected_count"] == 1
        assert dates["dates"] == ["2020-01-01"] and dates["has_more"] is False
        assert '"name": "store_query"' in events and '"status": "partial"' in events


async def test_single_snapshot_over_four_mib_preserves_default_and_max_page_target(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")
    count = 800
    model = QueryModel([
        ("store_data_catalog", {}),
        query([
            {"id": "oversized", "domain": "daily_ledger", "range": {"all_history": True},
             "fields": ["date", "activity"]},
            {"id": "dates", "domain": "daily_ledger", "range": {"all_history": True},
             "fields": ["date"]},
        ]),
        continue_target("dates", 200),
        echo_capacity_evidence,
    ])
    async with chat_app(tmp_path, model) as (client, _, factory):
        await seed_history(factory, count, "充" * 2000)
        batches, output, events = await public_evidence(client, await ask(client, "查询全部历史事件和日期，可续页"))
        first, second = batches
        oversized, dates = first["targets"]
        continued = second["targets"][0]
        assert first["status"] == "partial"
        assert oversized["error"] == "result_capacity_exceeded"
        assert oversized["returned_count"] == 0 and not oversized.get("result_ref")
        assert oversized["matched_count"] == oversized["selected_count"] == count
        assert dates["matched_count"] == dates["selected_count"] == count
        assert dates["returned_count"] == 50 and dates["page_range"] == {"start": 1, "end": 50}
        assert continued["returned_count"] == 200 and continued["page_range"] == {"start": 51, "end": 250}
        assert continued["result_ref"] == dates["result_ref"]
        expected = [(date(2020, 1, 1) + timedelta(days=index)).isoformat() for index in range(250)]
        assert dates["dates"] + continued["dates"] == expected
        assert continued["read_range"] == {"start": 1, "end": 250}
        assert continued["has_more"] and continued["next_cursor"]
        assert "部分完成" in output and "250/800" in output
        assert events.count('"name": "store_query"') == 2


async def test_cumulative_snapshot_capacity_preserves_prior_result_continuation(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")
    event = "存" * 2000
    count = 500
    target = {"domain": "daily_ledger", "range": {"all_history": True},
              "fields": ["date", "activity"], "page_size": 1}
    model = QueryModel([
        ("store_data_catalog", {}),
        query([{**target, "id": "retained"}, {**target, "id": "capacity_failure"}]),
        continue_target("retained", 2),
        echo_capacity_evidence,
    ])
    async with chat_app(tmp_path, model) as (client, _, factory):
        await seed_history(factory, count, event)
        batches, output, events = await public_evidence(client, await ask(client, "查询两组完整历史事件并继续读取第一组"))
        first, second = batches
        retained, failed = first["targets"]
        continued = second["targets"][0]
        assert first["status"] == "partial"
        assert retained["status"] == "partial" and retained["returned_count"] == 1
        assert retained["matched_count"] == retained["selected_count"] == count
        assert retained["result_ref"] and retained["next_cursor"]
        assert failed["error"] == "result_capacity_exceeded"
        assert failed["returned_count"] == 0 and not failed.get("result_ref")
        assert continued["result_ref"] == retained["result_ref"]
        assert continued["returned_count"] == 2 and continued["page_range"] == {"start": 2, "end": 3}
        assert continued["read_range"] == {"start": 1, "end": 3}
        assert retained["dates"] + continued["dates"] == ["2020-01-01", "2020-01-02", "2020-01-03"]
        expected_digest = hashlib.sha256(event.encode("utf-8")).hexdigest()
        assert retained["activity_digests"] + continued["activity_digests"] == [expected_digest] * 3
        assert continued["has_more"] and continued["next_cursor"]
        assert "部分完成" in output and "3/500" in output
        assert events.count('"name": "store_query"') == 2
