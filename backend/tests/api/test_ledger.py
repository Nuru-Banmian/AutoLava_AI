from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.identity import Store, StoreMember, User
from app.models.income_config import IncomeConfigVersion, IncomeConfigVersionItem
from app.models.ledger import IncomeCategory, StoreDailyRecord
from app.models.operations import DailyBriefing


@dataclass
class AssignedStore:
    store: Store
    cash: IncomeCategory
    excluded: IncomeCategory
    config: IncomeConfigVersion

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
    cash = IncomeCategory(
        store_id=store.id,
        name="Cash",
        include_in_total=True,
        is_active=True,
        sort_order=0,
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
    config = IncomeConfigVersion(
        store_id=store.id,
        version=1,
        enabled=True,
        created_by=user.id,
        items=[
            IncomeConfigVersionItem(
                category_id=category.id,
                name=category.name,
                include_in_total=category.include_in_total,
                is_active=True,
                sort_order=category.sort_order,
            )
            for category in (cash, excluded)
        ],
    )
    db_session.add(config)
    await db_session.flush()
    return AssignedStore(store=store, cash=cash, excluded=excluded, config=config)


@pytest.fixture
def ledger_payload(assigned_store: AssignedStore) -> dict:
    return {
        "is_open": "营业",
        "wash_count": 12,
        "weather": "晴",
        "weather_edited": True,
        "activity": None,
        "config_version_id": assigned_store.config.id,
        "items": [
            {"category_id": assigned_store.cash.id, "amount": "200.00"},
            {"category_id": assigned_store.excluded.id, "amount": "80.00"},
        ],
    }


def today_for(assigned_store: AssignedStore) -> date:
    return datetime.now(ZoneInfo(assigned_store.store.timezone)).date()


async def test_standard_put_does_not_attempt_external_weather_http(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    weather_stub,
    respx_mock,
) -> None:
    record_date = today_for(assigned_store)
    external = respx_mock.get("https://api.open-meteo.com/v1/forecast").mock(
        side_effect=AssertionError("ordinary ledger test attempted external weather")
    )

    response = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}", json=ledger_payload
    )

    assert response.status_code == 201
    assert external.called is False
    assert weather_stub.daily_calls == [(assigned_store.id, record_date)]


async def test_stale_expected_version_cannot_overwrite(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    record_date = today_for(assigned_store)
    path = f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}"
    created = await auth_client.put(path, json=ledger_payload)
    assert created.status_code == 201
    assert created.json()["row_version"] == 1

    updated = await auth_client.put(
        path + "?overwrite=true",
        json=ledger_payload | {"expected_version": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["row_version"] == 2

    stale = await auth_client.put(
        path + "?overwrite=true",
        json=ledger_payload | {"expected_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "Record changed; reload before saving"


async def test_stale_expected_version_cannot_delete(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    record_date = today_for(assigned_store)
    path = f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}"
    assert (await auth_client.put(path, json=ledger_payload)).status_code == 201

    stale = await auth_client.delete(path, params={"expected_version": 2})
    assert stale.status_code == 409
    assert stale.json()["detail"] == "Record changed; reload before saving"
    assert (await auth_client.get(path)).status_code == 200


async def test_form_config_uses_current_config_then_record_snapshot(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    record_date = today_for(assigned_store)
    path = f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}"
    before = await auth_client.get(path + "/form-config")
    assert before.status_code == 200
    assert before.json()["version_id"] == assigned_store.config.id
    assert [item["name"] for item in before.json()["items"]] == ["Cash", "Excluded"]

    assert (await auth_client.put(path, json=ledger_payload)).status_code == 201
    assigned_store.cash.name = "Renamed later"
    after = await auth_client.get(path + "/form-config")
    assert after.status_code == 200
    assert [item["name"] for item in after.json()["items"]] == ["Cash", "Excluded"]


async def test_put_injects_trusted_weather_and_preserves_manual_weather(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    open_meteo_app,
    respx_mock,
) -> None:
    record_date = today_for(assigned_store)
    respx_mock.get("https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(
            200,
            json={
                "daily": {
                    "time": [record_date.isoformat()],
                    "weather_code": [2],
                    "temperature_2m_max": [27.5],
                    "temperature_2m_min": [18.1],
                    "precipitation_sum": [0.2],
                }
            },
        )
    )
    forged = ledger_payload | {
        "weather_auto": "伪造",
        "weather_code": 999,
        "temperature_max": 99,
        "precipitation": 99,
    }

    created = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}", json=forged
    )
    assert created.status_code == 201
    record = await auth_client.get(
        f"/api/ledger/{assigned_store.id}", params={"date": record_date.isoformat()}
    )
    assert record.json()["weather"] == "晴"
    assert record.json()["weather_auto"] == "多云"
    assert record.json()["weather_code"] == 2
    assert record.json()["temperature_max"] == "27.50"
    assert record.json()["precipitation"] == "0.20"


async def test_put_still_saves_when_weather_lookup_fails(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    open_meteo_app,
    respx_mock,
) -> None:
    record_date = today_for(assigned_store)
    respx_mock.get("https://api.open-meteo.com/v1/forecast").mock(
        side_effect=httpx.TimeoutException("slow")
    )

    response = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}", json=ledger_payload
    )

    assert response.status_code == 201


async def test_create_update_and_delete_refresh_persisted_today_briefing(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
) -> None:
    record_date = today_for(assigned_store)
    path = f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}"

    created = await auth_client.put(path, json=ledger_payload)
    assert created.status_code == 201
    cards = (await auth_client.get(f"/api/dashboard/{assigned_store.id}")).json()
    assert next(card for card in cards if card["card_type"] == "today")["content"] == (
        "今天：天气暂时不可用；已记账，营业额 €200.00。"
    )

    updated = await auth_client.put(
        path + "?overwrite=true",
        json=ledger_payload | {"expected_version": 1, "items": [
            {"category_id": assigned_store.cash.id, "amount": "321.00"},
            {"category_id": assigned_store.excluded.id, "amount": "80.00"},
        ]},
    )
    assert updated.status_code == 200
    cards = (await auth_client.get(f"/api/dashboard/{assigned_store.id}")).json()
    assert "€321.00" in next(card for card in cards if card["card_type"] == "today")["content"]

    deleted = await auth_client.delete(path, params={"expected_version": 2})
    assert deleted.status_code == 204
    cards = (await auth_client.get(f"/api/dashboard/{assigned_store.id}")).json()
    assert "还未记账" in next(card for card in cards if card["card_type"] == "today")["content"]


async def test_briefing_refresh_failure_does_not_undo_committed_ledger(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_refresh(*_args, **_kwargs):
        raise RuntimeError("briefing storage unavailable")

    monkeypatch.setattr("app.api.routes.ledger._refresh_briefing_after_commit", fail_refresh)
    record_date = today_for(assigned_store)
    response = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}", json=ledger_payload
    )
    assert response.status_code == 201
    stored = await auth_client.get(
        f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}"
    )
    assert stored.status_code == 200


async def test_briefing_sql_then_failure_keeps_normal_put_response_and_commit(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def sql_then_fail(service, *_args, **_kwargs):
        await service.session.scalar(select(func.count()).select_from(DailyBriefing))
        raise RuntimeError("briefing failed after SQL")

    monkeypatch.setattr("app.services.briefing.BriefingService.regenerate", sql_then_fail)
    record_date = today_for(assigned_store)
    store_id = assigned_store.id
    response = await auth_client.put(
        f"/api/ledger/{store_id}/{record_date.isoformat()}", json=ledger_payload
    )
    assert response.status_code == 201
    assert response.json() == {
        "id": response.json()["id"],
        "date": record_date.isoformat(),
            "daily_revenue": "200.00",
            "row_version": 1,
    }
    stored = await auth_client.get(
        f"/api/ledger/{store_id}/{record_date.isoformat()}"
    )
    assert stored.status_code == 200
    assert stored.json()["daily_revenue"] == "200.00"


async def test_same_date_requires_overwrite_flag(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    path = f"/api/ledger/{assigned_store.id}/{today_for(assigned_store).isoformat()}"
    assert (await auth_client.put(path, json=ledger_payload)).status_code == 201
    response = await auth_client.put(path, json=ledger_payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "Record exists; confirm overwrite"
    assert (
        await auth_client.put(
            path + "?overwrite=true", json=ledger_payload | {"expected_version": 1}
        )
    ).status_code == 200


async def test_put_recomputes_revenue_and_get_by_query_returns_full_record(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    record_date = today_for(assigned_store)
    created = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}", json=ledger_payload
    )

    assert created.status_code == 201
    assert created.json()["daily_revenue"] == "200.00"
    response = await auth_client.get(
        f"/api/ledger/{assigned_store.id}", params={"date": record_date.isoformat()}
    )
    assert response.status_code == 200
    assert response.json()["id"] == created.json()["id"]
    assert response.json()["date"] == record_date.isoformat()
    assert response.json()["daily_revenue"] == "200.00"
    assert [item["amount"] for item in response.json()["items"]] == ["200.00", "80.00"]
    assert response.json()["created_at"]
    assert response.json()["items"][0]["created_at"]


async def test_get_by_date_path_alias_does_not_shadow_recent_route(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    record_date = today_for(assigned_store)
    path = f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}"
    assert (await auth_client.put(path, json=ledger_payload)).status_code == 201

    by_path = await auth_client.get(path)
    recent = await auth_client.get(f"/api/ledger/{assigned_store.id}/recent")

    assert by_path.status_code == 200
    assert by_path.json()["date"] == record_date.isoformat()
    assert recent.status_code == 200
    assert [item["date"] for item in recent.json()] == [record_date.isoformat()]


async def test_recent_uses_store_local_calendar_window_and_descending_order(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    today = today_for(assigned_store)
    dates = [today - timedelta(days=7), today - timedelta(days=2), today]
    for record_date in dates:
        response = await auth_client.put(
            f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}", json=ledger_payload
        )
        assert response.status_code == 201

    recent = await auth_client.get(f"/api/ledger/{assigned_store.id}/recent", params={"days": 7})

    assert recent.status_code == 200
    assert [item["date"] for item in recent.json()] == [
        today.isoformat(),
        (today - timedelta(days=2)).isoformat(),
    ]


async def test_rest_day_is_normalized_but_weather_closure_is_retained(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    today = today_for(assigned_store)
    rest_payload = ledger_payload | {"is_open": "休息", "wash_count": 8}
    rest = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{(today - timedelta(days=1)).isoformat()}",
        json=rest_payload,
    )
    assert rest.status_code == 201
    rest_record = await auth_client.get(
        f"/api/ledger/{assigned_store.id}",
        params={"date": (today - timedelta(days=1)).isoformat()},
    )
    assert rest_record.json()["wash_count"] == 0
    assert rest_record.json()["daily_revenue"] == "0.00"
    assert {item["amount"] for item in rest_record.json()["items"]} == {"0.00"}

    closure_payload = ledger_payload | {"is_open": "天气停业", "wash_count": 3}
    closure = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{today.isoformat()}", json=closure_payload
    )
    assert closure.status_code == 201
    closure_record = await auth_client.get(
        f"/api/ledger/{assigned_store.id}", params={"date": today.isoformat()}
    )
    assert closure_record.json()["wash_count"] == 3
    assert closure_record.json()["daily_revenue"] == "200.00"
    assert [item["amount"] for item in closure_record.json()["items"]] == [
        "200.00",
        "80.00",
    ]


async def test_future_date_is_rejected(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    response = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/2999-01-01", json=ledger_payload
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Future ledger dates are not allowed"}


async def test_duplicate_items_are_rejected_before_database_write(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    db_session: AsyncSession,
) -> None:
    duplicate = ledger_payload | {
        "items": [
            {"category_id": assigned_store.cash.id, "amount": "10.00"},
            {"category_id": assigned_store.cash.id, "amount": "20.00"},
        ]
    }

    response = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{today_for(assigned_store).isoformat()}",
        json=duplicate,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Duplicate income categories are not allowed"}
    assert await db_session.scalar(select(func.count()).select_from(StoreDailyRecord)) == 0


async def test_category_from_another_store_is_rejected(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    db_session: AsyncSession,
    store_factory,
) -> None:
    other_store = await store_factory(name="Unrelated")
    category = IncomeCategory(
        store_id=other_store.id,
        name="Foreign",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add(category)
    await db_session.flush()
    ledger_payload["items"] = [{"category_id": category.id, "amount": "10.00"}]

    response = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{today_for(assigned_store).isoformat()}",
        json=ledger_payload,
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Every active income item must be provided exactly once"
    }


@pytest.mark.parametrize(
    ("amount", "error_type"),
    [
        ("0.005", "decimal_max_places"),
        ("10000000000.00", "decimal_whole_digits"),
    ],
)
async def test_api_schema_enforces_numeric_amount_contract(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    db_session: AsyncSession,
    amount: str,
    error_type: str,
) -> None:
    ledger_payload["items"] = [{"category_id": assigned_store.cash.id, "amount": amount}]

    response = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{today_for(assigned_store).isoformat()}",
        json=ledger_payload,
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == error_type
    assert await db_session.scalar(select(func.count()).select_from(StoreDailyRecord)) == 0


async def test_delete_returns_204_and_writes_delete_audit(
    auth_client: AsyncClient,
    assigned_store: AssignedStore,
    ledger_payload: dict,
    db_session: AsyncSession,
) -> None:
    record_date = today_for(assigned_store)
    path = f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}"
    created = await auth_client.put(path, json=ledger_payload)
    assert created.status_code == 201

    deleted = await auth_client.delete(path, params={"expected_version": 1})

    assert deleted.status_code == 204
    assert deleted.content == b""
    missing = await auth_client.get(
        f"/api/ledger/{assigned_store.id}", params={"date": record_date.isoformat()}
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Record not found"}
    audit = await db_session.scalar(
        select(AuditLog)
        .where(
            AuditLog.operation_domain == "ledger",
            AuditLog.record_id == created.json()["id"],
            AuditLog.operation_type == "delete",
        )
        .order_by(AuditLog.id.desc())
    )
    assert audit is not None
    assert audit.before_json["daily_revenue"] == "200.00"
    assert audit.after_json is None


@pytest.mark.parametrize(
    ("method", "path_kind"),
    [
        ("put", "date"),
        ("get", "query"),
        ("get", "recent"),
        ("delete", "date"),
    ],
)
async def test_unassigned_store_is_uniformly_invisible(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    store_factory,
    method: str,
    path_kind: str,
) -> None:
    store = await store_factory(name="Invisible")
    record_date = datetime.now(ZoneInfo(store.timezone)).date()
    category = IncomeCategory(
        store_id=store.id,
        name="Cash",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add(category)
    await db_session.flush()
    payload = {
        "is_open": "营业",
        "wash_count": 1,
        "items": [{"category_id": category.id, "amount": "10.00"}],
    }
    if path_kind == "recent":
        path = f"/api/ledger/{store.id}/recent"
        params = None
    elif path_kind == "query":
        path = f"/api/ledger/{store.id}"
        params = {"date": record_date.isoformat()}
    else:
        path = f"/api/ledger/{store.id}/{record_date.isoformat()}"
        params = None

    response = await auth_client.request(
        method, path, params=params, json=payload if method == "put" else None
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Store not found"}


async def test_missing_and_inactive_stores_are_indistinguishable(
    auth_client: AsyncClient, store_factory
) -> None:
    inactive = await store_factory(name="Inactive", is_active=False)

    inactive_response = await auth_client.get(
        f"/api/ledger/{inactive.id}", params={"date": date.today().isoformat()}
    )
    missing_response = await auth_client.get(
        "/api/ledger/999999", params={"date": date.today().isoformat()}
    )

    assert inactive_response.status_code == missing_response.status_code == 404
    assert inactive_response.json() == missing_response.json() == {"detail": "Store not found"}


async def test_request_validation_rejects_invalid_amount_status_and_recent_days(
    auth_client: AsyncClient, assigned_store: AssignedStore, ledger_payload: dict
) -> None:
    record_date = today_for(assigned_store)
    invalid_amount = ledger_payload | {
        "items": [{"category_id": assigned_store.cash.id, "amount": "-0.01"}]
    }
    amount_response = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}", json=invalid_amount
    )
    invalid_status = await auth_client.put(
        f"/api/ledger/{assigned_store.id}/{record_date.isoformat()}",
        json=ledger_payload | {"is_open": "unknown"},
    )
    invalid_days = await auth_client.get(
        f"/api/ledger/{assigned_store.id}/recent", params={"days": 0}
    )

    assert amount_response.status_code == 422
    assert invalid_status.status_code == 422
    assert invalid_days.status_code == 422
