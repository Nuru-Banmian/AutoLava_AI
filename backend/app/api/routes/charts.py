from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import Session, StoreAccess, require_store_read_access
from app.models.ledger import IncomeCategory
from app.schemas.charts import ChartsResponse
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/charts", tags=["charts"])


@router.get("/{store_id}", response_model=ChartsResponse)
async def get_charts(
    start: date,
    end: date,
    session: Session,
    access: Annotated[StoreAccess, Depends(require_store_read_access)],
    category_id: Annotated[list[int] | None, Query()] = None,
    compare_start: date | None = None,
    compare_end: date | None = None,
    bucket: Literal["day", "month"] = "day",
) -> ChartsResponse:
    if start > end:
        raise HTTPException(422, "start must be on or before end")
    if (compare_start is None) != (compare_end is None):
        raise HTTPException(422, "compare_start and compare_end must be provided together")
    if compare_start is not None and compare_end is not None and compare_start > compare_end:
        raise HTTPException(422, "compare_start must be on or before compare_end")

    selected_ids = None if category_id is None else list(dict.fromkeys(category_id))
    if selected_ids is not None:
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
        compare_start=compare_start,
        compare_end=compare_end,
        bucket=bucket,
    )
    return ChartsResponse.model_validate(result)
