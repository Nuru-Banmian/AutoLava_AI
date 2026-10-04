"""Independent complete-income examples through HTTP and migrated temporary SQLite."""

from sqlalchemy import update

from app.models.ledger import StoreDailyRecord
from tests.api.test_charts_groups_migrated import group_analysis, save_day, get_groups

# Importing this fixture makes the existing migrated public-API harness available here.
__all__ = ["group_analysis"]


async def test_total_classified_snapshot_difference_and_historical_settlement(group_analysis):
    client, store_id, factory = group_analysis
    await save_day(client, store_id, "2026-07-01", 100)
    configured = await client.put(f"/api/admin/stores/{store_id}/income-config", json={
        "expected_revision": 1, "enabled": True,
        "items": [{"name": "现金", "include_in_total": True},
                  {"name": "其他数据", "include_in_total": False}],
    })
    assert configured.status_code == 200, configured.text
    config = configured.json()
    cash, other = config["items"]
    await save_day(client, store_id, "2026-07-02", None, config_revision=config["revision"],
                   items=[{"category_id": cash["id"], "amount": 25},
                          {"category_id": other["id"], "amount": 900}])
    # A historical imported ledger can contain a difference from its classified snapshots.
    async with factory() as session:
        await session.execute(update(StoreDailyRecord).where(
            StoreDailyRecord.store_id == store_id, StoreDailyRecord.date == "2026-07-02"
        ).values(daily_revenue=75))
        await session.commit()
    renamed = await client.patch(f"/api/admin/income-categories/{cash['id']}", json={
        "expected_revision": config["revision"], "name": "新名称", "include_in_total": False,
    })
    assert renamed.status_code == 200, renamed.text
    company = await client.post(f"/api/settlements/{store_id}/companies", json={"name": "测试公司"})
    assert company.status_code == 201, company.text
    records = []
    for amount in (325, 800):
        record = await client.post(f"/api/settlements/{store_id}/records", json={
            "company_id": company.json()["id"], "opening_month": "2026-07", "amount": amount,
        })
        assert record.status_code == 201, record.text
        records.append(record.json())
    confirmed = await client.post(f"/api/settlements/{store_id}/records/{records[0]['id']}/confirm",
                                  json={"revision": records[0]["revision"]})
    assert confirmed.status_code == 200, confirmed.text
    disabled = await client.patch(f"/api/admin/stores/{store_id}",
                                  json={"company_settlement_enabled": False})
    assert disabled.status_code == 200, disabled.text
    expected = [
        {"category_id": cash["id"], "category_name": "现金", "amount": 25},
        {"category_id": None, "category_name": "未分类营业额", "amount": 150},
        {"category_id": None, "category_name": "公司结算", "amount": 325},
    ]
    for query in ("start=2026-07-01&end=2026-07-02",
                  f"start=2026-07-01&end=2026-07-31&category_id={other['id']}",
                  "start=2026-07-01&end=2026-08-31&bucket=month"):
        result = await get_groups(client, store_id, query)
        assert result["income_composition"] == expected
        assert result["income_summary"] == {
            "daily_ledger_revenue": 175, "confirmed_settlement_income": 325,
            "total_income": 500, "includes_settlement_income": True,
        }
        assert result["excluded_categories"] == [
            {"category_id": other["id"], "category_name": "其他数据", "amount": 900},
        ]
    partial = await get_groups(client, store_id, "start=2026-07-02&end=2026-07-02")
    assert partial["income_summary"]["total_income"] == 400
    assert partial["income_composition"][1]["amount"] == 50
    empty = await get_groups(client, store_id, "start=2026-08-01&end=2026-08-31")
    assert empty["income_composition"] == []
    assert empty["income_summary"]["total_income"] == 0
    assert empty["income_summary"]["includes_settlement_income"] is False
