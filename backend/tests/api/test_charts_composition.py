"""Complete income composition at the public HTTP boundary."""

from datetime import date

from app.models.ledger import IncomeCategory
from tests.api.test_charts import _assigned_store, _confirmed_settlement, _record


async def test_complete_composition_keeps_filtered_categories_compatible(
    auth_client, db_session, store_factory
):
    store = await _assigned_store(auth_client, db_session, store_factory)
    cash = IncomeCategory(store_id=store.id, name="现金", include_in_total=True)
    other = IncomeCategory(store_id=store.id, name="其他数据", include_in_total=False)
    db_session.add_all([cash, other])
    await db_session.flush()
    await _record(db_session, store, cash, revenue=125, category_amount=25)
    await _record(db_session, store, other, record_date=date(2026, 7, 13),
                  revenue=75, category_amount=900)
    await _confirmed_settlement(db_session, store, opening_month=date(2026, 7, 1), amount=300)

    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-07-12&end=2026-07-13&category_id={other.id}"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["income_composition"] == [
        {"category_id": cash.id, "category_name": "现金", "amount": 25},
        {"category_id": None, "category_name": "未分类营业额", "amount": 175},
        {"category_id": None, "category_name": "公司结算", "amount": 300},
    ]
    assert payload["income_summary"]["total_income"] == 500
    assert payload["income_summary"]["includes_settlement_income"] is True
    assert sum(row["amount"] for row in payload["income_composition"]) == 500
    assert payload["categories"][0] == {
        "category_id": other.id, "category_name": "其他数据", "amount": 900,
    }
    assert payload["classified_included_total"] == 325
