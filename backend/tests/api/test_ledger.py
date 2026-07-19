from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store, StoreMember, User
from app.models.ledger import IncomeCategory


@dataclass
class AssignedStore:
    store: Store
    cash: IncomeCategory
    excluded: IncomeCategory

    @property
    def id(self) -> int:
        return self.store.id


@pytest.fixture
async def assigned_store(
    auth_client: AsyncClient, db_session: AsyncSession, store_factory
) -> AssignedStore:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    store = await store_factory(name="Assigned", timezone="Europe/Berlin")
    store.income_items_enabled = True
    cash = IncomeCategory(
        store_id=store.id, name="Cash", include_in_total=True, is_active=True, sort_order=0
    )
    excluded = IncomeCategory(
        store_id=store.id,
        name="Excluded",
        include_in_total=False,
        is_active=True,
        sort_order=1,
    )
    db_session.add_all([StoreMember(store_id=store.id, user_id=user.id), cash, excluded])
    await db_session.flush()
    return AssignedStore(store, cash, excluded)


@pytest.fixture
def ledger_payload(assigned_store: AssignedStore) -> dict:
    return {
        "is_open": "营业",
        "daily_revenue": None,
        "wash_count": 12,
        "weather": "晴",
        "weather_edited": True,
        "activity": None,
        "items": [
            {"category_id": assigned_store.cash.id, "amount": 200},
            {"category_id": assigned_store.excluded.id, "amount": 80},
        ],
    }


def today_for(assigned_store: AssignedStore) -> date:
    return datetime.now(ZoneInfo(assigned_store.store.timezone)).date()


@pytest.mark.parametrize("amount", [1.5, "1.00"])
async def test_amount_input_requires_json_integer(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    amount,
) -> None:
    ledger_payload["items"][0]["amount"] = amount
    response = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{today_for(assigned_store).isoformat()}",
        json=ledger_payload,
    )
    assert response.status_code == 422


@pytest.mark.parametrize("daily_revenue", [1.5, "1.00"])
async def test_direct_total_requires_json_integer(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    db_session: AsyncSession,
    daily_revenue,
) -> None:
    assigned_store.store.income_items_enabled = False
    await db_session.flush()
    response = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{today_for(assigned_store).isoformat()}",
        json={"is_open": "营业", "daily_revenue": daily_revenue, "items": []},
    )
    assert response.status_code == 422


async def test_second_put_overwrites_without_compatibility_parameters(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    path = f"/api/ledger/{assigned_store.id}/{today_for(assigned_store).isoformat()}"
    first = await auth_client.put(path, json=ledger_payload)
    second_payload = ledger_payload | {
        "items": [
            {"category_id": assigned_store.cash.id, "amount": 321},
            {"category_id": assigned_store.excluded.id, "amount": 90},
        ]
    }
    second = await auth_client.put(path, json=second_payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["daily_revenue"] == 321


async def test_record_snapshot_is_retained_after_current_category_edits(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    db_session: AsyncSession,
) -> None:
    path = f"/api/ledger/{assigned_store.id}/{today_for(assigned_store).isoformat()}"
    assert (await auth_client.put(path, json=ledger_payload)).status_code == 201
    assigned_store.cash.name = "Renamed"
    assigned_store.cash.include_in_total = False
    assigned_store.cash.sort_order = 8
    assigned_store.excluded.name = "Excluded renamed"
    assigned_store.excluded.include_in_total = True
    assigned_store.excluded.sort_order = 9
    await db_session.flush()

    updated = await auth_client.put(
        path,
        json=ledger_payload
        | {
            "items": [
                {"category_id": assigned_store.cash.id, "amount": 125},
                {"category_id": assigned_store.excluded.id, "amount": 75},
            ]
        },
    )
    fetched = await auth_client.get(path)
    assert updated.status_code == 200
    assert updated.json()["daily_revenue"] == 125
    assert [
        (item["category_name"], item["include_in_total"], item["sort_order"])
        for item in fetched.json()["items"]
    ] == [("Cash", True, 0), ("Excluded", False, 1)]


async def test_put_and_get_return_integer_money(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    path = f"/api/ledger/{assigned_store.id}/{today_for(assigned_store).isoformat()}"
    created = await auth_client.put(path, json=ledger_payload)
    fetched = await auth_client.get(path)
    assert created.status_code == 201
    assert created.json()["daily_revenue"] == 200
    assert fetched.json()["daily_revenue"] == 200
    assert [item["amount"] for item in fetched.json()["items"]] == [200, 80]


async def test_recent_uses_store_local_window(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    today = today_for(assigned_store)
    for target in (today - timedelta(days=7), today - timedelta(days=2), today):
        response = await auth_client.put(
            f"/api/ledger/{assigned_store.id}/{target.isoformat()}", json=ledger_payload
        )
        assert response.status_code == 201
    recent = await auth_client.get(
        f"/api/ledger/{assigned_store.id}/recent", params={"days": 7}
    )
    assert [item["date"] for item in recent.json()] == [
        today.isoformat(),
        (today - timedelta(days=2)).isoformat(),
    ]


async def test_future_and_invalid_status_are_422(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    future = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/2999-01-01", json=ledger_payload
    )
    invalid = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{today_for(assigned_store).isoformat()}",
        json=ledger_payload | {"is_open": "unknown"},
    )
    assert future.status_code == invalid.status_code == 422


async def test_delete_returns_204(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    db_session: AsyncSession,
) -> None:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    user.role = "admin"
    await db_session.flush()
    path = f"/api/ledger/{assigned_store.id}/{today_for(assigned_store).isoformat()}"
    assert (await auth_client.put(path, json=ledger_payload)).status_code == 201
    deleted = await auth_client.delete(path)
    assert deleted.status_code == 204
    assert (await auth_client.get(path)).status_code == 404
