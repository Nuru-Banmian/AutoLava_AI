from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import Store, User
from app.models.income_config import IncomeConfigVersion, IncomeConfigVersionItem
from app.models.ledger import DailyIncomeItem, IncomeCategory
from app.schemas.income_config import (
    IncomeConfigItemBody,
    IncomeConfigItemResponse,
    IncomeConfigPublishBody,
    IncomeConfigResponse,
)
from app.services.audit import add_admin_audit


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
    def _formula(items: list[IncomeConfigVersionItem]) -> str:
        included = [
            item.name
            for item in sorted(items, key=lambda item: (item.sort_order, item.id))
            if item.is_active and item.include_in_total
        ]
        return "总收入 = " + " + ".join(included) if included else "总收入 = €0.00"

    @classmethod
    def response(cls, version: IncomeConfigVersion | None, *, store_id: int) -> IncomeConfigResponse:
        if version is None:
            return IncomeConfigResponse(
                store_id=store_id,
                version_id=None,
                version=0,
                enabled=False,
                formula="总收入 = €0.00",
                items=[],
            )
        ordered = sorted(version.items, key=lambda item: (item.sort_order, item.id))
        return IncomeConfigResponse(
            store_id=store_id,
            version_id=version.id,
            version=version.version,
            enabled=version.enabled,
            formula=cls._formula(ordered),
            created_at=version.created_at,
            items=[IncomeConfigItemResponse.model_validate(item) for item in ordered],
        )

    async def current(self, store_id: int) -> IncomeConfigVersion | None:
        await self._require_store(store_id)
        return await self.session.scalar(
            select(IncomeConfigVersion)
            .where(IncomeConfigVersion.store_id == store_id)
            .options(selectinload(IncomeConfigVersion.items))
            .order_by(IncomeConfigVersion.version.desc())
            .limit(1)
        )

    async def versions(self, store_id: int) -> list[IncomeConfigVersion]:
        await self._require_store(store_id)
        return list(
            await self.session.scalars(
                select(IncomeConfigVersion)
                .where(IncomeConfigVersion.store_id == store_id)
                .options(selectinload(IncomeConfigVersion.items))
                .order_by(IncomeConfigVersion.version.desc())
            )
        )

    @staticmethod
    def _validate_unique(body: IncomeConfigPublishBody) -> None:
        ids = [item.category_id for item in body.items if item.category_id is not None]
        names = [item.name.casefold() for item in body.items]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, "Duplicate income category IDs are not allowed")
        if len(names) != len(set(names)):
            raise HTTPException(422, "Duplicate income category names are not allowed")

    async def publish(
        self,
        store_id: int,
        body: IncomeConfigPublishBody,
        actor: User,
        *,
        operation_type: str = "config_publish",
    ) -> IncomeConfigVersion:
        await self._require_store(store_id, for_update=True)
        self._validate_unique(body)
        await self.session.execute(
            select(IncomeConfigVersion.id)
            .where(IncomeConfigVersion.store_id == store_id)
            .with_for_update()
        )

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

        existing_names = {
            category.name.casefold()
            for category in await self.session.scalars(
                select(IncomeCategory).where(IncomeCategory.store_id == store_id)
            )
            if category.id not in requested_ids
        }
        next_version = (
            await self.session.scalar(
                select(func.coalesce(func.max(IncomeConfigVersion.version), 0)).where(
                    IncomeConfigVersion.store_id == store_id
                )
            )
        ) + 1
        version = IncomeConfigVersion(
            store_id=store_id,
            version=next_version,
            enabled=body.enabled,
            created_by=actor.id,
            items=[],
        )
        self.session.add(version)
        await self.session.flush()

        for item in body.items:
            category = categories.get(item.category_id)
            if category is not None and category.archived_at is not None:
                continue
            if category is None:
                if item.name.casefold() in existing_names:
                    raise HTTPException(422, "Income category name already exists")
                category = IncomeCategory(
                    store_id=store_id,
                    name=item.name,
                    include_in_total=item.include_in_total,
                    is_active=item.is_active,
                    sort_order=item.sort_order,
                )
                self.session.add(category)
                await self.session.flush()
                existing_names.add(item.name.casefold())
            else:
                category.name = item.name
                category.include_in_total = item.include_in_total
                category.is_active = item.is_active
                category.sort_order = item.sort_order
            version.items.append(
                IncomeConfigVersionItem(
                    category_id=category.id,
                    name=item.name,
                    include_in_total=item.include_in_total,
                    is_active=item.is_active,
                    sort_order=item.sort_order,
                )
            )

        await self.session.flush()
        await self.session.refresh(version, attribute_names=["created_at"])
        add_admin_audit(
            self.session,
            actor_id=actor.id,
            store_id=store_id,
            record_id=None,
            operation_type=operation_type,
            description=f"Published income configuration version {version.version}",
            before=None,
            after=self.response(version, store_id=store_id).model_dump(mode="json"),
        )
        await self.session.flush()
        return version

    async def publish_categories(
        self, store_id: int, actor: User, *, enabled: bool | None = None
    ) -> IncomeConfigVersion:
        current = await self.current(store_id)
        categories = list(
            await self.session.scalars(
                select(IncomeCategory)
                .where(
                    IncomeCategory.store_id == store_id,
                    IncomeCategory.archived_at.is_(None),
                )
                .order_by(IncomeCategory.sort_order, IncomeCategory.id)
            )
        )
        return await self.publish(
            store_id,
            IncomeConfigPublishBody(
                enabled=(current.enabled if current is not None else bool(categories))
                if enabled is None
                else enabled,
                items=[
                    IncomeConfigItemBody(
                        category_id=category.id,
                        name=category.name,
                        include_in_total=category.include_in_total,
                        is_active=category.is_active,
                        sort_order=category.sort_order,
                    )
                    for category in categories
                ],
            ),
            actor,
        )

    async def restore(self, store_id: int, version_id: int, actor: User) -> IncomeConfigVersion:
        source = await self.session.scalar(
            select(IncomeConfigVersion)
            .where(
                IncomeConfigVersion.id == version_id,
                IncomeConfigVersion.store_id == store_id,
            )
            .options(selectinload(IncomeConfigVersion.items))
        )
        if source is None:
            raise HTTPException(404, "Income configuration version not found")
        items: list[IncomeConfigItemBody] = []
        for snapshot in source.items:
            category = (
                None
                if snapshot.category_id is None
                else await self.session.get(IncomeCategory, snapshot.category_id)
            )
            if category is None:
                category = IncomeCategory(
                    store_id=store_id,
                    name=snapshot.name,
                    include_in_total=snapshot.include_in_total,
                    is_active=snapshot.is_active,
                    sort_order=snapshot.sort_order,
                )
                self.session.add(category)
                await self.session.flush()
            elif category.store_id != store_id:
                raise HTTPException(409, "Income configuration version is not restorable")
            category.archived_at = None
            items.append(
                IncomeConfigItemBody(
                    category_id=category.id,
                    name=snapshot.name,
                    include_in_total=snapshot.include_in_total,
                    is_active=snapshot.is_active,
                    sort_order=snapshot.sort_order,
                )
            )
        return await self.publish(
            store_id,
            IncomeConfigPublishBody(enabled=source.enabled, items=items),
            actor,
            operation_type="config_restore",
        )

    async def archive(self, category_id: int, actor: User) -> IncomeCategory:
        category = await self.session.get(IncomeCategory, category_id, with_for_update=True)
        if category is None:
            raise HTTPException(404, "Category not found")
        category.archived_at = datetime.now(UTC).replace(tzinfo=None)
        category.is_active = False
        await self.session.flush()
        await self.publish_categories(category.store_id, actor)
        return category

    async def restore_category(self, category_id: int, actor: User) -> IncomeCategory:
        category = await self.session.get(IncomeCategory, category_id, with_for_update=True)
        if category is None:
            raise HTTPException(404, "Category not found")
        before = {"archived_at": category.archived_at.isoformat() if category.archived_at else None}
        category.archived_at = None
        category.is_active = False
        add_admin_audit(
            self.session,
            actor_id=actor.id,
            store_id=category.store_id,
            record_id=category.id,
            operation_type="restore",
            description=f"Restored income category {category.name}",
            before=before,
            after={"archived_at": None, "is_active": False},
        )
        await self.session.flush()
        return category

    async def delete_unused(self, category_id: int, actor: User) -> None:
        category = await self.session.get(IncomeCategory, category_id, with_for_update=True)
        if category is None:
            raise HTTPException(404, "Category not found")
        used = await self.session.scalar(
            select(DailyIncomeItem.id).where(DailyIncomeItem.category_id == category_id).limit(1)
        )
        if used is not None:
            raise HTTPException(409, "Used categories must be archived")
        add_admin_audit(
            self.session,
            actor_id=actor.id,
            store_id=category.store_id,
            record_id=category.id,
            operation_type="delete",
            description=f"Deleted income category {category.name}",
            before={"id": category.id, "name": category.name},
            after=None,
        )
        store_id = category.store_id
        await self.session.delete(category)
        await self.session.flush()
        await self.publish_categories(store_id, actor)
