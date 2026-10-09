"""No Agent pagination: bounded complete rows and independent smaller-range queries."""
from datetime import date, timedelta

from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_store_query import QueryModel, query
from tests.api.test_agent_tools import ask


def latest_batch(model):
    return next(value for value in reversed(model.results) if "targets" in value)


async def save_event(client, day, amount, event):
    old = await client.get(f"/api/ledger/1/{day}")
    data = old.json() if old.status_code == 200 else {}
    response = await client.put(f"/api/ledger/1/{day}", json={
        "expected_identity": data.get("identity"), "expected_revision": data.get("revision"),
        "expected_config_revision": 1, "is_open": "营业", "daily_revenue": amount,
        "activity": event,
    })
    assert response.status_code in (200, 201), response.text


async def test_long_detail_returns_partial_without_cursor_or_auto_queries(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([{
        "id":"all", "domain":"daily_ledger", "range":{"start":"2026-06-01","end":"2026-07-30"},
        "fields":["date","daily_revenue","activity"]}]),
        "部分明细已返回，需要更小日期范围继续查询。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        event = "完整事件不能截断。" * 70
        for i in range(60):
            day = (date(2026,6,1)+timedelta(days=i)).isoformat()
            await save_event(client,day,i,event)
        run = await ask(client,"逐页读完全部60天明细")
        assert run["status"] == "completed", run
        batches = [r for r in model.results if "targets" in r]
        assert len(batches) == 1
        target = batches[0]["targets"][0]
        assert target["matched_count"] == 60 and target["status"] == "partial"
        assert 0 < len(target["rows"]) < 60
        assert all(r["activity"] == event for r in target["rows"])
        assert "next_cursor" not in target and "has_more" not in target
        assert "仅部分完成" in run["output"] and "更小日期范围" in run["output"]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert events.count('"name": "store_query"') == 1


async def test_smaller_followup_queries_latest_data_with_new_reference(tmp_path):
    target = {"id":"days","domain":"daily_ledger","range":{"start":"2026-07-01","end":"2026-07-03"},
              "fields":["date","daily_revenue"],"row_limit":1}
    followup = {**target,"range":{"start":"2026-07-02","end":"2026-07-02"}}
    model = QueryModel([("store_data_catalog",{}),query([target]),"仅返回第一天。",
                        ("store_data_catalog",{}),query([followup]),"最新7月2日金额999。"])
    async with chat_app(tmp_path,model) as (client,_,_):
        for day in range(1,4):
            await save_event(client,f"2026-07-{day:02}",day,"记录")
        first=await ask(client,"查询三天明细")
        assert first["status"] == "completed",first
        old=latest_batch(model)["targets"][0]
        await save_event(client,"2026-07-02",999,"最新记录")
        second=await ask(client,"细查2026年7月2日明细")
        assert second["status"] == "completed",second
        current=latest_batch(model)["targets"][0]
        assert current["rows"] == [{"date":"2026-07-02","daily_revenue":999}]
        assert current["result_ref"] != old["result_ref"]
        assert not current["unread_ranges"] and "next_cursor" not in current
