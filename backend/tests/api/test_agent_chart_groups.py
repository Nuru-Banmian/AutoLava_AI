"""Chart extensions through authenticated HTTP/SSE and migrated SQLite."""
import json

import pytest

from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_pagination import latest_batch
from tests.api.test_agent_store_query import QueryModel, query
from tests.api.test_agent_tools import ask, save_day


@pytest.fixture(autouse=True)
def semantic_budget(monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")


def chart(**options):
    def action(model):
        target = latest_batch(model)["targets"][0]
        return "store_chart", {"operation": "create", "result_ref": target["result_ref"],
                               "dimension": "day", "series": ["total_revenue"],
                               "type": "line", "title": "经营数据", **options}
    return action


async def saved(client):
    message = (await client.get("/api/agent/1/conversation")).json()["messages"][-1]
    snapshots = []
    for description in message["charts"]:
        response = await client.get(f"/api/agent/1/messages/{message['id']}/charts/{description['chart_id']}")
        assert response.status_code == 200, response.text
        snapshots.append(response.json())
    return snapshots


async def test_grouped_comparison_splits_units_with_identical_range_and_grain(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "income", "domain": "monthly_income",
        "range": {"start": "2026-07-01", "end": "2026-08-31"},
        "metrics": ["daily_ledger_revenue", "confirmed_settlement_income", "total_wash_count"],
        "group_by": ["month"],
    }]), chart(type="grouped_bar", dimension="month",
               series=["daily_ledger_revenue", "confirmed_settlement_income", "total_wash_count"]),
        "金额与数量分别展示。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        run = await ask(client, "比较两月收入与数量，分图")
        assert run["status"] == "completed", run
        assert model.results[-1].get("status") == "prepared", model.results[-1]
        charts = await saved(client)
        assert [c["payload"]["unit"] for c in charts] == ["EUR", "辆"]
        first, second = [c["payload"] for c in charts]
        assert first["range"] == second["range"] == {"start": "2026-07-01", "end": "2026-08-31"}
        assert first["granularity"] == second["granularity"] == "month"
        assert first["points"][0]["values"]["daily_ledger_revenue"]["exact"] == "19"
        assert len(first["series"]) == 2
        sse = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert sse.count('"name": "store_query"') == 1
        receipt = json.loads(sse.split("event: completed\ndata: ")[1].split("\n")[0])
        assert len(receipt["charts"]) == 2 and "points" not in sse


async def seed_composition(client):
    response = await client.put("/api/admin/stores/1/income-config", json={
        "expected_revision": 1, "enabled": True,
        "items": [{"name": "现金", "include_in_total": True},
                  {"name": "刷卡", "include_in_total": True}],
    })
    assert response.status_code == 200, response.text
    config = response.json()
    for day, amounts in [("2026-07-01", [25, 75]), ("2026-08-01", [40, 0])]:
        response = await client.put(f"/api/ledger/1/{day}", json={
            "expected_identity": None, "expected_revision": None,
            "expected_config_revision": config["revision"], "is_open": "营业",
            "items": [{"category_id": item["id"], "amount": amount}
                      for item, amount in zip(config["items"], amounts, strict=True)],
        })
        assert response.status_code == 201, response.text


def composition_query():
    return query([{"id": "parts", "domain": "income_composition",
                   "range": {"start": "2026-07-01", "end": "2026-09-30"},
                   "metrics": ["amount"], "group_by": ["month", "category"]}])


async def test_income_composition_pivots_categories_and_keeps_zero_and_unknown(tmp_path):
    model = QueryModel([("store_data_catalog", {}), composition_query(),
                       chart(type="stacked_bar", dimension="month", series=["amount"], series_by="category"),
                       "收入构成已展示，九月无已统计台账。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await seed_composition(client)
        run = await ask(client, "三个完整月收入构成堆叠图")
        assert run["status"] == "completed", run
        assert model.results[-1].get("status") == "prepared", model.results[-1]
        payload = (await saved(client))[0]["payload"]
        assert payload["type"] == "stacked_bar"
        assert [p["dimension"] for p in payload["points"]] == ["2026-07", "2026-08", "2026-09"]
        labels = {s["label"]: s["key"] for s in payload["series"]}
        assert set(labels) == {"现金", "刷卡"}
        assert payload["points"][0]["values"][labels["现金"]]["exact"] == "25"
        assert payload["points"][0]["values"][labels["刷卡"]]["exact"] == "75"
        assert payload["points"][1]["values"][labels["刷卡"]]["exact"] == "0"
        assert payload["points"][2]["values"][labels["现金"]]["exact"] is None


async def test_stacked_chart_rejects_overlapping_total_and_components(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "overlap", "domain": "monthly_income",
        "range": {"start": "2026-07-01", "end": "2026-07-31"},
        "metrics": ["daily_ledger_revenue", "total_income"], "group_by": ["month"],
    }]), chart(type="stacked_bar", dimension="month", series=["daily_ledger_revenue", "total_income"]),
        "图表已生成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        run = await ask(client, "收入堆叠图")
        assert model.results[-1].get("error") == "chart_incompatible_stack", model.results[-1]
        assert "图表请求未生成" in run["output"]
        assert await saved(client) == []


@pytest.mark.parametrize("top_n,expected", [(3, ["2026-07-02", "2026-07-03", "2026-07-01"]), (None, None)])
async def test_horizontal_ranking_uses_explicit_selection_and_preserves_order(tmp_path, top_n, expected):
    target = {"id": "rank", "domain": "daily_ledger",
              "range": {"start": "2026-07-01", "end": "2026-07-04"},
              "fields": ["date", "daily_revenue", "activity"],
              "order_by": [{"field": "daily_revenue", "direction": "desc"}]}
    if top_n:
        target["top_n"] = top_n
    model = QueryModel([("store_data_catalog", {}), query([target]),
                       chart(type="horizontal_bar", dimension="date", series=["daily_revenue"]), "排名结果。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        for day, amount in [(1, 19), (2, 99), (3, 40), (4, 0)]:
            await save_day(client, f"2026-07-{day:02}", amount)
        run = await ask(client, "营业额最高三天" if top_n else "画排名")
        assert run["status"] == "completed", run
        if expected:
            assert model.results[-1].get("status") == "prepared", model.results[-1]
            payload = (await saved(client))[0]["payload"]
            assert [p["dimension"] for p in payload["points"]] == expected
            assert [p["values"]["daily_revenue"]["exact"] for p in payload["points"]] == ["99", "40", "19"]
        else:
            assert model.results[-1].get("error") == "chart_explicit_ranking_required", model.results[-1]
            assert await saved(client) == []

def long_query(end="2026-07-04"):
    return query([{"id": "long", "domain": "daily_ledger",
                   "range": {"start": "2024-01-01", "end": end},
                   "metrics": ["total_revenue"], "group_by": ["day"], "row_limit": 2}])


async def test_long_trend_keeps_all_days_and_a_common_vertical_axis(tmp_path):
    model = QueryModel([("store_data_catalog", {}), long_query(), chart(), "完整逐日趋势分三段。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2024-01-01", 19)
        await save_day(client, "2026-07-04", 99)
        run = await ask(client, "全部逐日趋势，不改粒度")
        assert run["status"] == "completed", run
        assert model.results[-1].get("status") == "prepared", model.results[-1]
        payloads = [c["payload"] for c in await saved(client)]
        assert [len(p["points"]) for p in payloads] == [366, 366, 184]
        assert [p["segment"]["index"] for p in payloads] == [1, 2, 3]
        assert all(p["segment"]["count"] == 3 for p in payloads)
        assert all(p["segment"]["total_range"] == {"start": "2024-01-01", "end": "2026-07-04"} for p in payloads)
        assert all(p["y_domain"] == [0, 99] for p in payloads)
        days = [point["dimension"] for p in payloads for point in p["points"]]
        assert len(set(days)) == 916 and days[0] == "2024-01-01" and days[-1] == "2026-07-04"
        assert payloads[0]["range"]["end"] == "2024-12-31"
        assert payloads[1]["range"]["start"] == "2025-01-01"
        assert payloads[-1]["points"][-1]["values"]["total_revenue"]["exact"] == "99"


async def test_segment_capacity_is_atomic_across_repeated_create_calls(tmp_path):
    model = QueryModel([("store_data_catalog", {}), long_query(), chart(), chart(), chart(),
                       "全部图已完成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2024-01-01", 19)
        run = await ask(client, "本轮重复创建三组长趋势")
        assert run["status"] == "completed", run
        assert model.results[-1].get("error") == "chart_capacity_exceeded", model.results[-1]
        prepared = [r for r in model.results if r.get("status") == "prepared"]
        assert [len(r["charts"]) for r in prepared] == [3, 3]
        charts = await saved(client)
        assert len(charts) == 6
        assert [c["chart_id"] for c in charts] == [d["chart_id"] for r in prepared for d in r["charts"]]
        assert "图表请求未生成" in run["output"]


@pytest.mark.parametrize("count", [50, 51])
async def test_category_ranking_limit_never_silently_truncates(tmp_path, count):
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "rank", "domain": "daily_ledger",
        "range": {"start": "2026-01-01", "end": "2026-03-31"},
        "metrics": ["total_revenue"], "group_by": ["day"], "top_n": count,
        "order_by": [{"field": "total_revenue", "direction": "desc"}], "row_limit": 2,
    }]), chart(type="horizontal_bar"), "按明确选择作图。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-01-01", 19)
        run = await ask(client, f"前{count}天排名")
        assert run["status"] == "completed", run
        charts = await saved(client)
        if count == 50:
            assert len(charts) == 1 and len(charts[0]["payload"]["points"]) == 50
        else:
            assert model.results[-1].get("error") == "chart_capacity_exceeded"
            assert charts == []


async def test_unit_split_group_rejection_retains_previous_success(tmp_path):
    metrics = ["total_revenue", "average_ledger_revenue", "average_revenue_per_car", "min_revenue", "max_revenue", "total_wash_count"]
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "many", "domain": "daily_ledger", "range": {"start": "2025-01-01", "end": "2025-12-31"},
        "metrics": metrics, "group_by": ["day"], "row_limit": 2,
    }]), chart(series=["total_wash_count"]), chart(series=metrics), "全部图已生成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2025-01-01", 19)
        run = await ask(client, "一次多单位整组超出单图容量")
        assert run["status"] == "completed", run
        assert model.results[-1].get("error") == "chart_capacity_exceeded"
        charts = await saved(client)
        assert len(charts) == 1 and charts[0]["payload"]["unit"] == "辆"
        assert "图表请求未生成" in run["output"]


async def test_default_budget_still_reports_chart_success_or_explicit_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOLAVA_AGENT_CONTEXT_CHARS")
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "short", "domain": "daily_ledger", "range": {"start": "2026-07-01", "end": "2026-07-04"},
        "metrics": ["total_revenue"], "group_by": ["day"],
    }]), chart(type="grouped_bar"), "图表已准备。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        run = await ask(client, "画营业额柱状图")
        assert run["status"] == "completed", run
        assert model.results[-1].get("status") == "prepared", model.results[-1]
        assert len(await saved(client)) == 1


async def test_composition_amount_and_percent_have_separate_units_and_exact_decimals(tmp_path):
    from tests.api.test_charts_daily_migrated import confirm_settlement
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "parts", "domain": "income_composition", "range": {"start": "2026-07-01", "end": "2026-08-31"},
        "metrics": ["amount", "share_percent"], "group_by": ["month", "category"],
    }]), chart(type="grouped_bar", dimension="month", series=["amount", "share_percent"], series_by="category"),
        "金额与占比分图，结算按开票月计入。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await seed_composition(client)
        assert (await client.patch("/api/admin/stores/1", json={"company_settlement_enabled": True})).status_code == 200
        await confirm_settlement(client, 1, "2026-07", 200)
        run = await ask(client, "收入构成金额与占比")
        assert run["status"] == "completed", run
        charts = await saved(client)
        assert [c["payload"]["unit"] for c in charts] == ["EUR", "%"]
        percent = charts[1]["payload"]
        cash = next(s["key"] for s in percent["series"] if s["label"] == "现金")
        assert percent["points"][0]["values"][cash] == {"exact": "8.33", "plot": 8.33, "status": "available"}


async def test_unsafe_value_rejects_entire_unit_group_without_fabricated_plot(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "unsafe", "domain": "daily_ledger", "range": {"start": "2026-07-01", "end": "2026-07-01"},
        "metrics": ["total_revenue", "total_wash_count"], "group_by": ["day"],
    }]), chart(series=["total_revenue", "total_wash_count"]), "图表全部生成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        response = await client.put("/api/ledger/1/2026-07-01", json={
            "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
            "is_open": "营业", "daily_revenue": 19, "wash_count": 9007199254740992,
        })
        assert response.status_code == 201, response.text
        run = await ask(client, "金额数量分图")
        assert run["status"] == "completed", run
        assert model.results[-1].get("error") == "chart_unsafe_value", model.results[-1]
        assert await saved(client) == []
        assert "图表请求未生成" in run["output"]


async def test_ranking_cannot_pivot_and_reorder_selected_category_rows(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "rank", "domain": "income_items", "range": {"start": "2026-07-01", "end": "2026-08-31"},
        "metrics": ["amount"], "group_by": ["weekday", "category"], "top_n": 2,
        "order_by": [{"field": "amount", "direction": "desc"}],
    }]), chart(type="horizontal_bar", dimension="weekday", series=["amount"], series_by="category"),
        "排名已完成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await seed_composition(client)
        run = await ask(client, "按星期分类金额取最高两项")
        assert run["status"] == "completed", run
        assert model.results[-1].get("error") == "invalid_chart_source", model.results[-1]
        assert await saved(client) == []
