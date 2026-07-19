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
