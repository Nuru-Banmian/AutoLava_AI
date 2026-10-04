"""Complete analysis acceptance with synthetic data and the shared local-service harness."""

from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[1]


def prepare(api, database):
    store = api("POST", "/admin/stores", {
        "name": "T6 可控长门店名称完整经营分析验收", "address": "Synthetic address",
        "latitude": "45", "longitude": "9", "timezone": "Europe/Rome",
    })
    store_id = store["id"]
    api("PATCH", f"/admin/stores/{store_id}", {"company_settlement_enabled": True})
    api("PUT", f"/ledger/{store_id}/2026-07-01", {
        "expected_config_revision": 1, "expected_identity": None, "expected_revision": None,
        "is_open": "营业", "daily_revenue": 100, "weather": "晴", "weather_edited": True,
    })
    config = api("PUT", f"/admin/stores/{store_id}/income-config", {
        "expected_revision": 1, "enabled": True,
        "items": [{"name": f"收入分类{i + 1}超长名称验证手机金额和比例完整可读",
                   "include_in_total": True} for i in range(13)]
                 + [{"name": "独立其他数据", "include_in_total": False}],
    })
    categories = config["items"]
    api("PUT", f"/ledger/{store_id}/2026-07-02", {
        "expected_config_revision": config["revision"],
        "expected_identity": None, "expected_revision": None, "is_open": "提前休息",
        "weather": "小雨", "weather_edited": True,
        "items": [{"category_id": item["id"],
                   "amount": 999900000 if index == 0 else 900 if index == 13 else 10}
                  for index, item in enumerate(categories)],
    })
    company = api("POST", f"/settlements/{store_id}/companies", {"name": "T6 可控公司"})
    for amount in (325, 800):
        record = api("POST", f"/settlements/{store_id}/records", {
            "company_id": company["id"], "opening_month": "2026-07", "amount": amount,
        })
        if amount == 325:
            api("POST", f"/settlements/{store_id}/records/{record['id']}/confirm",
                {"revision": record["revision"]})
    api("PATCH", f"/admin/stores/{store_id}", {"company_settlement_enabled": False})
    actual = api("GET", f"/charts/{store_id}?start=2026-07-01&end=2026-07-31")
    # Worked fixture: €999,900,000 + twelve €10 categories + €100 total-only + €325 confirmed.
    assert actual["income_summary"]["total_income"] == 999900545
    assert actual["income_summary"]["daily_ledger_revenue"] == 999900220
    assert [row["amount"] for row in actual["income_composition"]] == [999900000] + [10] * 12 + [100, 325]
    assert actual["excluded_categories"][0]["amount"] == 900
    return {"composition_store": store_id, "composition_categories": categories}


if __name__ == "__main__":
    harness = runpy.run_path(str(ROOT / "scripts" / "verify-issue-227-live.py"))
    harness["main"](prepare=prepare,
                    test_match=["grouped-performance-live.spec.ts", "income-composition-live.spec.ts", "analysis-protections-live.spec.ts",
                                "company-settlement-live.spec.ts"],
                    artifacts=ROOT / ".autolava-test" / "issue-228")
