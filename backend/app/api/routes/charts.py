from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import Session, StoreAccess, require_store_access
from app.models.ledger import IncomeCategory
from app.schemas.charts import ChartsResponse
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/charts", tags=["charts"])


@router.get("/{store_id}", response_model=ChartsResponse)
async def get_charts(
    start: date,
    end: date,
    session: Session,
    access: Annotated[StoreAccess, Depends(require_store_access)],
    category_id: Annotated[list[int] | None, Query()] = None,
) -> ChartsResponse:
    if start > end:
        raise HTTPException(422, "start must be on or before end")

    if category_id is None:
        selected_ids = list(
            await session.scalars(
                select(IncomeCategory.id)
                .where(
                    IncomeCategory.store_id == access.store.id,
                    IncomeCategory.include_in_total.is_(True),
                )
                .order_by(IncomeCategory.sort_order, IncomeCategory.id)
            )
        )
    else:
        selected_ids = list(dict.fromkeys(category_id))
        owned_ids = set(
            await session.scalars(
                select(IncomeCategory.id).where(
                    IncomeCategory.store_id == access.store.id,
                    IncomeCategory.id.in_(selected_ids),
                )
            )
        )
        if owned_ids != set(selected_ids):
            raise HTTPException(422, "All categories must belong to the requested store")

    result = await AnalyticsService(session).calculate(
        store_id=access.store.id,
        start=start,
        end=end,
        category_ids=selected_ids,
    )
    return ChartsResponse.model_validate(result)
