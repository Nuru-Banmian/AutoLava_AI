import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.ledger import IncomeCategory
from app.schemas.income_config import IncomeConfigPublishBody
from app.services.income_config import IncomeConfigService


async def test_replace_keeps_one_current_configuration_without_versions(
    db_session, store_factory
) -> None:
    store = await store_factory(name="Current configuration")
    service = IncomeConfigService(db_session)

    response = await service.replace(
        store.id,
        IncomeConfigPublishBody(
            enabled=True,
            items=[
                {"name": "现金", "include_in_total": True},
                {"name": "代收款", "include_in_total": False, "sort_order": 1},
            ],
        ),
    )

    assert response.store_id == store.id
    assert response.enabled is True
    assert response.formula == "营业额 = 现金；“代收款”只记录，不计入营业额"
    assert not hasattr(response, "version")
    assert [category.name for category in await db_session.scalars(
        select(IncomeCategory).order_by(IncomeCategory.sort_order)
    )] == ["现金", "代收款"]


async def test_replace_reorders_existing_categories_archives_omissions_and_formats_many_recorded_items(
    db_session, store_factory
) -> None:
    store = await store_factory(name="Replacement order")
    first = IncomeCategory(
        store_id=store.id, name="First", include_in_total=True, is_active=True, sort_order=0
    )
    second = IncomeCategory(
        store_id=store.id, name="Second", include_in_total=False, is_active=True, sort_order=1
    )
    omitted = IncomeCategory(
        store_id=store.id, name="Omitted", include_in_total=True, is_active=True, sort_order=2
    )
    db_session.add_all([first, second, omitted])
    await db_session.flush()

    response = await IncomeConfigService(db_session).replace(
        store.id,
        IncomeConfigPublishBody(
            enabled=True,
            items=[
                {"category_id": second.id, "name": "Second", "include_in_total": False, "sort_order": 99},
                {"category_id": first.id, "name": "First", "include_in_total": False, "sort_order": 77},
            ],
        ),
    )

    assert [(item.id, item.sort_order) for item in response.items] == [
        (second.id, 0),
        (first.id, 1),
    ]
    assert response.formula == "营业额 = 0；“Second”、“First”只记录，不计入营业额"
    await db_session.refresh(omitted)
    assert omitted.archived_at is not None
    assert omitted.is_active is False


async def test_replace_allows_new_category_to_reuse_omitted_category_name(
    db_session, store_factory
) -> None:
    store = await store_factory(name="Reuse name")
    existing = IncomeCategory(
        store_id=store.id, name="Cash", include_in_total=True, is_active=True, sort_order=0
    )
    db_session.add(existing)
    await db_session.flush()

    response = await IncomeConfigService(db_session).replace(
        store.id,
        IncomeConfigPublishBody(
            enabled=True,
            items=[{"name": "cash", "include_in_total": True}],
        ),
    )

    assert response.items[0].id != existing.id
    await db_session.refresh(existing)
    assert existing.archived_at is not None


@pytest.mark.parametrize(
    "items",
    [
        [
            {"name": "Cash", "include_in_total": True},
            {"name": "cash", "include_in_total": False},
        ],
    ],
)
async def test_replace_rejects_case_insensitive_duplicate_payload_names(
    db_session, store_factory, items
) -> None:
    store = await store_factory(name="Duplicate names")

    with pytest.raises(HTTPException, match="Duplicate income category names"):
        await IncomeConfigService(db_session).replace(
            store.id, IncomeConfigPublishBody(enabled=True, items=items)
        )


async def test_replace_rejects_duplicate_and_cross_store_category_ids(
    db_session, store_factory
) -> None:
    store = await store_factory(name="Target")
    other = await store_factory(name="Other")
    local = IncomeCategory(
        store_id=store.id, name="Local", include_in_total=True, is_active=True, sort_order=0
    )
    foreign = IncomeCategory(
        store_id=other.id, name="Foreign", include_in_total=True, is_active=True, sort_order=0
    )
    db_session.add_all([local, foreign])
    await db_session.flush()
    service = IncomeConfigService(db_session)

    with pytest.raises(HTTPException, match="Duplicate income category IDs"):
        await service.replace(
            store.id,
            IncomeConfigPublishBody(
                enabled=True,
                items=[
                    {"category_id": local.id, "name": "One", "include_in_total": True},
                    {"category_id": local.id, "name": "Two", "include_in_total": True},
                ],
            ),
        )
    with pytest.raises(HTTPException, match="does not belong"):
        await service.replace(
            store.id,
            IncomeConfigPublishBody(
                enabled=True,
                items=[{"category_id": foreign.id, "name": "Foreign", "include_in_total": True}],
            ),
        )
