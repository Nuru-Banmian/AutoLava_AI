from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store
from app.models.ledger import DailyIncomeItem, IncomeCategory
from app.schemas.income_config import (
    IncomeConfigPublishBody,
    IncomeConfigResponse,
    IncomeCategoryResponse,
)


class IncomeConfigService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _require_store(self, store_id: int, *, for_update: bool = False) -> Store:
        statement = select(Store).where(Store.id == store_id)
        if for_update:
            statement = statement.with_for_update()
        store = await self.session.scalar(statement)
        if store is None:
            raise HTTPException(404, "Store not found")
        return store

    @staticmethod
    def _formula(items: list[IncomeCategory]) -> str:
        active = [item for item in items if item.is_active]
        included = [item.name for item in active if item.include_in_total]
        recorded_only = [item.name for item in active if not item.include_in_total]
        total = "营业额 = " + (" + ".join(included) if included else "0")
        if recorded_only:
            quoted = "、“".join(recorded_only)
            total += f"；“{quoted}”只记录，不计入营业额"
        return total

    @classmethod
    def response(cls, store: Store, categories: list[IncomeCategory]) -> IncomeConfigResponse:
        ordered = sorted(categories, key=lambda item: (item.sort_order, item.id))
        return IncomeConfigResponse(
            store_id=store.id,
            enabled=store.income_items_enabled,
            formula=cls._formula(ordered),
            items=[IncomeCategoryResponse.model_validate(item) for item in ordered],
        )

    async def _current_categories(self, store_id: int) -> list[IncomeCategory]:
        return list(
            await self.session.scalars(
                select(IncomeCategory)
                .where(
                    IncomeCategory.store_id == store_id,
                    IncomeCategory.archived_at.is_(None),
                )
                .order_by(IncomeCategory.sort_order, IncomeCategory.id)
            )
        )

    async def current(self, store_id: int) -> IncomeConfigResponse:
        store = await self._require_store(store_id)
        return self.response(store, await self._current_categories(store_id))

    @staticmethod
    def _validate_unique(body: IncomeConfigPublishBody) -> None:
        ids = [item.category_id for item in body.items if item.category_id is not None]
        names = [item.name.casefold() for item in body.items]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, "Duplicate income category IDs are not allowed")
        if len(names) != len(set(names)):
            raise HTTPException(422, "Duplicate income category names are not allowed")

    async def replace(
        self, store_id: int, body: IncomeConfigPublishBody
    ) -> IncomeConfigResponse:
        store = await self._require_store(store_id, for_update=True)
        self._validate_unique(body)
        requested_ids = {item.category_id for item in body.items if item.category_id is not None}
        categories = {
            category.id: category
            for category in await self.session.scalars(
                select(IncomeCategory)
                .where(IncomeCategory.id.in_(requested_ids))
                .with_for_update()
            )
        }
        if set(categories) != requested_ids or any(
            category.store_id != store_id for category in categories.values()
        ):
            raise HTTPException(422, "Income category does not belong to this store")

        current = {
            category.id: category
            for category in await self.session.scalars(
                select(IncomeCategory)
                .where(IncomeCategory.store_id == store_id)
                .with_for_update()
            )
        }
        existing_names = {
            category.name.casefold()
            for category in current.values()
            if category.id not in requested_ids
        }
        for item in body.items:
            category = categories.get(item.category_id)
            if category is None:
                if item.name.casefold() in existing_names:
                    raise HTTPException(422, "Income category name already exists")
                category = IncomeCategory(store_id=store_id)
                self.session.add(category)
                existing_names.add(item.name.casefold())
            category.name = item.name
            category.include_in_total = item.include_in_total
            category.is_active = item.is_active
            category.sort_order = item.sort_order
            category.archived_at = None

        now = datetime.now(UTC).replace(tzinfo=None)
        for category in current.values():
            if category.id not in requested_ids and category.archived_at is None:
                category.archived_at = now
                category.is_active = False
        store.income_items_enabled = body.enabled
        await self.session.flush()
        return self.response(store, await self._current_categories(store_id))

    async def archive(self, category_id: int) -> IncomeCategory:
        category = await self.session.get(IncomeCategory, category_id, with_for_update=True)
        if category is None:
            raise HTTPException(404, "Category not found")
        category.archived_at = datetime.now(UTC).replace(tzinfo=None)
        category.is_active = False
        await self.session.flush()
        return category

    async def restore_category(self, category_id: int) -> IncomeCategory:
        category = await self.session.get(IncomeCategory, category_id, with_for_update=True)
        if category is None:
            raise HTTPException(404, "Category not found")
        category.archived_at = None
        category.is_active = False
        await self.session.flush()
        return category

    async def delete_unused(self, category_id: int) -> None:
        category = await self.session.get(IncomeCategory, category_id, with_for_update=True)
        if category is None:
            raise HTTPException(404, "Category not found")
        used = await self.session.scalar(
            select(DailyIncomeItem.id).where(DailyIncomeItem.category_id == category_id).limit(1)
        )
        if used is not None:
            raise HTTPException(409, "此收入项目已有历史记录，只能归档，不能永久删除")
        await self.session.delete(category)
        await self.session.flush()
