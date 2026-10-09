"""#264 acceptance through authenticated chat and forward-migrated SQLite."""
from datetime import datetime
import pytest

from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_store_query import QueryModel, query
from tests.api.test_agent_tools import ask, save_day


def freeze_today(monkeypatch, year=2026, month=10, day=9):
    import app.agents.tools.store_catalog as module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(year, month, day, 12, tzinfo=tz)

    monkeypatch.setattr(module, "datetime", Clock)


async def test_ledger_metrics_use_all_matches_and_quantity_coverage(tmp_path, monkeypatch):
    freeze_today(monkeypatch)
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "summary", "domain": "daily_ledger",
        "range": {"start": "2026-10-05", "end": "2026-10-09"},
        "metrics": ["total_revenue", "operating_days", "average_ledger_revenue",
                    "total_wash_count", "average_revenue_per_car", "min_revenue", "max_revenue"],
    }]), "已统计台账150欧元，经营日3天，数量覆盖2个经营日。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-10-05", 100, wash=2)
        await save_day(client, "2026-10-06", 50)
        await save_day(client, "2026-10-07", None, "未统计")
        await save_day(client, "2026-10-08", 0, "休息")
        await save_day(client, "2026-10-09", 0, wash=0)
        run = await ask(client, "本周经营指标汇总")
        assert run["status"] == "completed", run
        result = model.results[-1]["targets"][0]
        assert result["status"] == "complete", result
        assert result["metrics"] == {
            "total_revenue": 150, "operating_days": 3, "average_ledger_revenue": 50,
            "total_wash_count": 2, "average_revenue_per_car": 50,
            "min_revenue": 0, "max_revenue": 100,
        }
        assert result["coverage"]["statistical_days"] == 4
        assert result["coverage"]["unreported_days"] == 1
        assert result["coverage"]["wash_count_covered_days"] == 2
        assert result["coverage"]["wash_count_missing_operating_days"] == 1
        assert result["denominators"]["average_revenue_per_car"] == 2
        assert result["metric_metadata"]["average_ledger_revenue"][0] == "EUR"


async def test_grouped_ranking_keeps_full_totals_and_unknown_days(tmp_path, monkeypatch):
    freeze_today(monkeypatch)
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "rank", "domain": "daily_ledger", "range": {"preset": "this_week"},
        "metrics": ["total_revenue"], "group_by": ["day"],
        "order_by": [{"field": "total_revenue", "direction": "desc"}], "top_n": 2,
    }, {
        "id": "trend", "domain": "daily_ledger", "range": {"preset": "this_week"},
        "metrics": ["total_revenue"], "group_by": ["day"],
    }]), "排名只选两天，合计仍按全匹配台账计算。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-10-05", 100)
        await save_day(client, "2026-10-06", 250)
        await save_day(client, "2026-10-07", None, "未统计")
        await save_day(client, "2026-10-08", 0, "休息")
        run = await ask(client, "本周收入最高两天及本周日趋势")
        assert run["status"] == "completed", run
        rank, trend = model.results[-1]["targets"]
        assert rank["metrics"]["total_revenue"] == 350
        assert rank["matched_count"] == 5 and rank["selected_count"] == 2
        assert [r["day"] for r in rank["rows"]] == ["2026-10-06", "2026-10-05"]
        assert [r["rank"] for r in rank["rows"]] == [1, 2]
        assert [r["metrics"]["total_revenue"] for r in trend["rows"]] == [100, 250, None, 0, None]
        assert [r["state"] for r in trend["rows"]] == ["营业", "营业", "未统计", "休息", "未录入"]


async def test_current_week_comparison_and_daily_data_need_one_query(tmp_path, monkeypatch):
    freeze_today(monkeypatch)
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "comparison", "domain": "daily_ledger", "range": {"preset": "this_week"},
        "metrics": ["total_revenue", "operating_days", "average_ledger_revenue"],
        "compare": {"preset": "previous_period"},
    }, {
        "id": "trend", "domain": "daily_ledger", "range": {"preset": "this_week"},
        "metrics": ["total_revenue"], "group_by": ["day"],
    }]), "本周同进度台账收入150欧元，上周200欧元，减少50欧元、25%。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-09-28", 200)
        await save_day(client, "2026-10-03", 999)  # Saturday is outside Friday's progress.
        await save_day(client, "2026-10-05", 100)
        await save_day(client, "2026-10-09", 50)
        run = await ask(client, "本周与上周同进度比较并显示本周日数据")
        assert run["status"] == "completed", run
        result, trend = model.results[-1]["targets"]
        previous = result["comparison"]
        assert previous["range"] == {"start": "2026-09-28", "end": "2026-10-02"}
        assert previous["metrics"]["total_revenue"] == 200
        assert previous["changes"]["total_revenue"] == {
            "difference": -50, "change_percent": -25.0, "status": "comparable",
            "unit": "EUR", "denominator": 200,
        }
        assert len(trend["rows"]) == 5
        events = await client.get(f"/api/agent/1/runs/{run['id']}/events")
        assert events.text.count('"name": "store_query"') == 1
        assert events.text.count('"name": "store_data_catalog"') == 1
        assert '"name": "calculate"' not in events.text


@pytest.mark.parametrize("current,previous,status,percent", [
    (None, 100, "no_current_records", None),
    (0, 100, "comparable", -100.0),
    (50, 0, "zero_previous", None),
    (50, None, "no_previous_records", None),
])
async def test_comparison_distinguishes_unknown_and_known_zero(tmp_path, monkeypatch,
                                                               current, previous, status, percent):
    freeze_today(monkeypatch)
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "compare", "domain": "daily_ledger", "range": {"preset": "this_week"},
        "metrics": ["total_revenue"], "compare": {},
    }]), "已区分已知零值和无可统计台账。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-10-05", current, "未统计" if current is None else "营业")
        await save_day(client, "2026-09-28", previous, "未统计" if previous is None else "营业")
        run = await ask(client, "本周与上周同进度比较")
        assert run["status"] == "completed", run
        change = model.results[-1]["targets"][0]["comparison"]["changes"]["total_revenue"]
        assert change["status"] == status
        assert change["change_percent"] == percent
        if current is None or previous is None:
            assert change["difference"] is None


async def test_filters_groups_and_invalid_combinations_preserve_success(tmp_path, monkeypatch):
    freeze_today(monkeypatch)
    targets = [
        {"id": "weather", "domain": "daily_ledger", "range": {"preset": "this_week"},
         "metrics": ["total_revenue", "operating_days"], "group_by": ["weather", "weekday"],
         "filters": [{"field": "weekday", "op": "in", "value": [0, 1]}]},
        {"id": "mixed", "domain": "daily_ledger", "fields": ["date"], "metrics": ["total_revenue"]},
        {"id": "calendar", "domain": "daily_ledger", "metrics": ["total_revenue"], "group_by": ["day", "month"]},
        {"id": "disabled", "domain": "daily_ledger", "metrics": ["total_wash_count", "average_revenue_per_car"]},
    ]
    model = QueryModel([("store_data_catalog", {}), query(targets), "有效目标保留；关闭的数量指标不可用。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        for day, amount, weather in [("2026-10-05", 100, "晴"), ("2026-10-06", 250, "小雨"),
                                     ("2026-10-07", 40, "晴")]:
            response = await client.put(f"/api/ledger/1/{day}", json={
                "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
                "is_open": "营业", "daily_revenue": amount, "wash_count": 2, "weather": weather})
            assert response.status_code == 201, response.text
        assert (await client.patch("/api/admin/stores/1", json={"wash_count_enabled": False})).status_code == 200
        run = await ask(client, "按记录天气与星期汇总并检查数量指标")
        assert run["status"] == "completed", (run, model.results)
        a, b, c, d = model.results[-1]["targets"]
        assert a["metrics"] == {"total_revenue": 350, "operating_days": 2}
        assert a["coverage"]["excluded_record_days"] == 1
        assert a["coverage"]["missing_record_days"] == 2
        assert all(r["coverage"]["missing_record_days"] is None for r in a["rows"])
        assert [(r["weather"], r["weekday"], r["metrics"]["total_revenue"]) for r in a["rows"]] == [("小雨", 1, 250), ("晴", 0, 100)]
        assert b["error"] == c["error"] == "invalid_query_target"
        assert d["metric_status"] == {"total_wash_count": "wash_count_disabled", "average_revenue_per_car": "wash_count_disabled"}


@pytest.mark.parametrize("first,last", [(0, 3), (3, 6)])
async def test_comparison_calendar_boundaries_and_explicit_dates(tmp_path, monkeypatch, first, last):
    freeze_today(monkeypatch, 2024, 3, 31)
    targets = [
        {"id": "month", "domain": "daily_ledger", "range": {"preset": "this_month"},
         "metrics": ["total_revenue"], "compare": {}},
        {"id": "complete", "domain": "daily_ledger", "range": {"preset": "last_month"},
         "metrics": ["total_revenue"], "compare": {}},
        {"id": "week", "domain": "daily_ledger", "range": {"preset": "this_week"},
         "metrics": ["total_revenue"], "compare": {}},
        {"id": "exact", "domain": "daily_ledger", "range": {"start": "2024-03-10", "end": "2024-03-12"},
         "metrics": ["total_revenue"], "compare": {"range": {"start": "2024-02-05", "end": "2024-02-09"}}},
        {"id": "year", "domain": "daily_ledger", "range": {"preset": "this_year"},
         "metrics": ["total_revenue"], "compare": {"preset": "same_period_last_year"}},
        {"id": "invalid", "domain": "daily_ledger", "metrics": ["total_revenue"],
         "compare": {"preset": "previous_period", "range": {"preset": "last_month"}}},
    ]
    model = QueryModel([("store_data_catalog", {}), query(targets[first:last]), "比较日期已明确；非法目标未执行。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        assert (await ask(client, "当前与完整周期、显式日期比较"))["status"] == "completed"
        results = model.results[-1]["targets"]
        expected = [
            {"start": "2024-02-01", "end": "2024-02-29"},
            {"start": "2024-01-01", "end": "2024-01-31"},
            {"start": "2024-03-18", "end": "2024-03-24"},
            {"start": "2024-02-05", "end": "2024-02-09"},
            {"start": "2023-01-01", "end": "2023-03-31"},
        ]
        assert [r["comparison"]["range"] for r in results[:min(5, last)-first]] == expected[first:min(5, last)]
        if last == 6:
            assert results[-1]["error"] == "invalid_query_target"
