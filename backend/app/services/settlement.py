from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import sqlite_short_write
from app.models.identity import Store
from app.models.ledger import StoreDailyRecord
from app.models.settlement import SettlementAuditEvent, SettlementCompany, SettlementRecord
from app.schemas.settlement import SettlementRecordResponse, parse_month
from app.services.access import require_company_settlement_access


def normalized_company_name(name: str) -> str:
    return name.casefold()


def company_state(company: SettlementCompany) -> dict[str, object]:
    return {"id": company.id, "name": company.name, "is_active": company.is_active}


class SettlementCompanyService:
    def __init__(self, session: AsyncSession, *, store_id: int, actor_id: int):
        self.session = session
        self.store_id = store_id
        self.actor_id = actor_id

    async def list(self, *, active: bool) -> list[SettlementCompany]:
        return list(
            (
                await self.session.scalars(
                    select(SettlementCompany)
                    .where(
                        SettlementCompany.store_id == self.store_id,
                        SettlementCompany.is_active.is_(active),
                    )
                    .order_by(SettlementCompany.normalized_name, SettlementCompany.id)
                )
            ).all()
        )

    async def get(self, company_id: int) -> SettlementCompany:
        company = await self.session.scalar(
            select(SettlementCompany).where(
                SettlementCompany.id == company_id,
                SettlementCompany.store_id == self.store_id,
            )
        )
        if company is None:
            raise HTTPException(404, "结算公司不存在")
        return company

    def audit(
        self,
        action: str,
        company_id: int | None,
        before: dict[str, object] | None,
        after: dict[str, object] | None,
    ) -> None:
        self.session.add(
            SettlementAuditEvent(
                store_id=self.store_id,
                actor_id=self.actor_id,
                action=action,
                entity_type="settlement_company",
                entity_id=company_id,
                before_state=before,
                after_state=after,
            )
        )

    async def recheck_access(self) -> None:
        await require_company_settlement_access(
            self.session, user_id=self.actor_id, store_id=self.store_id
        )

    async def create(self, name: str) -> SettlementCompany:
        try:
            async with sqlite_short_write(self.session):
                await self.recheck_access()
                company = SettlementCompany(
                    store_id=self.store_id,
                    name=name,
                    normalized_name=normalized_company_name(name),
                    is_active=True,
                    archived_at=None,
                    created_by=self.actor_id,
                    updated_by=self.actor_id,
                )
                self.session.add(company)
                await self.session.flush()
                self.audit("settlement_company.create", company.id, None, company_state(company))
        except IntegrityError as exc:
            raise HTTPException(409, "该门店已存在同名结算公司") from exc
        return company

    async def rename(self, company_id: int, name: str) -> SettlementCompany:
        try:
            async with sqlite_short_write(self.session):
                await self.recheck_access()
                company = await self.get(company_id)
                before = company_state(company)
                company.name = name
                company.normalized_name = normalized_company_name(name)
                company.updated_by = self.actor_id
                self.audit("settlement_company.rename", company.id, before, company_state(company))
        except IntegrityError as exc:
            raise HTTPException(409, "该门店已存在同名结算公司") from exc
        return company

    async def set_active(self, company_id: int, *, active: bool) -> SettlementCompany:
        try:
            async with sqlite_short_write(self.session):
                await self.recheck_access()
                company = await self.get(company_id)
                if company.is_active == active:
                    return company
                before = company_state(company)
                company.is_active = active
                company.archived_at = None if active else datetime.now(timezone.utc)
                company.updated_by = self.actor_id
                action = "settlement_company.restore" if active else "settlement_company.archive"
                self.audit(action, company.id, before, company_state(company))
        except IntegrityError as exc:
            raise HTTPException(409, "该门店已有同名活动结算公司，无法恢复") from exc
        return company

    async def delete(self, company_id: int) -> None:
        async with sqlite_short_write(self.session):
            await self.recheck_access()
            company = await self.get(company_id)
            references = await self.session.scalar(
                select(func.count())
                .select_from(SettlementRecord)
                .where(
                    SettlementRecord.store_id == self.store_id,
                    SettlementRecord.company_id == company.id,
                )
            )
            if references:
                raise HTTPException(409, "该结算公司已有开票历史，只能归档")
            before = company_state(company)
            await self.session.delete(company)
            self.audit("settlement_company.delete", company_id, before, None)


def record_state(record: SettlementRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "company_id": record.company_id,
        "company_name": record.company_name,
        "opening_month": record.opening_month.isoformat(),
        "amount": record.amount,
        "status": record.status,
        "revision": record.revision,
    }


class SettlementRecordService:
    def __init__(self, session: AsyncSession, *, store: Store, actor_id: int):
        self.session = session
        self.store = store
        self.store_id = store.id
        self.actor_id = actor_id

    async def recheck_access(self) -> Store:
        _, store = await require_company_settlement_access(
            self.session, user_id=self.actor_id, store_id=self.store_id
        )
        return store

    async def get(self, record_id: int) -> SettlementRecord:
        record = await self.session.scalar(
            select(SettlementRecord).where(
                SettlementRecord.id == record_id,
                SettlementRecord.store_id == self.store_id,
            )
        )
        if record is None:
            raise HTTPException(404, "当前门店的开票记录不存在")
        return record

    @staticmethod
    def require_pending(record: SettlementRecord) -> None:
        if record.status != "pending":
            raise HTTPException(409, "已确认开票记录必须先撤销到账确认")

    @staticmethod
    def require_revision(record: SettlementRecord, revision: int) -> None:
        if record.revision == revision:
            return
        current = SettlementRecordResponse.model_validate(record).model_dump(mode="json")
        raise HTTPException(
            409,
            {
                "code": "settlement_record_revision_conflict",
                "message": "开票记录已被其他用户修改，请重新加载后再试",
                "current_record": current,
            },
        )

    def validated_month(self, value: str) -> date:
        try:
            month = parse_month(value)
        except ValueError as exc:
            raise HTTPException(422, "开票月份必须是有效的 YYYY-MM") from exc
        current = datetime.now(ZoneInfo(self.store.timezone)).date().replace(day=1)
        if month > current:
            raise HTTPException(422, "开票月份不能位于未来")
        return month

    async def month(self, value: str) -> dict[str, object]:
        store = await self.recheck_access()
        self.store = store
        month = self.validated_month(value)
        if month.month == 12:
            next_month = date(month.year + 1, 1, 1)
        else:
            next_month = date(month.year, month.month + 1, 1)
        records = list(
            (
                await self.session.scalars(
                    select(SettlementRecord)
                    .where(
                        SettlementRecord.store_id == self.store_id,
                        SettlementRecord.opening_month == month,
                    )
                    .order_by(
                        SettlementRecord.status.desc(),
                        func.lower(SettlementRecord.company_name),
                        SettlementRecord.created_at,
                        SettlementRecord.id,
                    )
                )
            ).all()
        )
        daily_revenue = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(StoreDailyRecord.daily_revenue), 0)).where(
                    StoreDailyRecord.store_id == self.store_id,
                    StoreDailyRecord.date >= month,
                    StoreDailyRecord.date < next_month,
                )
            )
            or 0
        )
        confirmed = sum(record.amount for record in records if record.status == "confirmed")
        pending = sum(record.amount for record in records if record.status == "pending")
        return {
            "opening_month": month,
            "records": records,
            "daily_ledger_revenue": daily_revenue,
            "confirmed_settlement_income": confirmed,
            "pending_amount": pending,
            "monthly_total": daily_revenue + confirmed,
        }

    async def create(self, *, company_id: int, opening_month: str, amount: int) -> SettlementRecord:
        month = self.validated_month(opening_month)
        async with sqlite_short_write(self.session):
            store = await self.recheck_access()
            self.store = store
            month = self.validated_month(opening_month)
            company = await self.session.scalar(
                select(SettlementCompany).where(
                    SettlementCompany.id == company_id,
                    SettlementCompany.store_id == self.store_id,
                    SettlementCompany.is_active.is_(True),
                )
            )
            if company is None:
                raise HTTPException(404, "当前门店的活动结算公司不存在")
            record = SettlementRecord(
                store_id=self.store_id,
                company_id=company.id,
                company_name=company.name,
                opening_month=month,
                amount=amount,
                status="pending",
                revision=1,
                created_by=self.actor_id,
                updated_by=self.actor_id,
            )
            self.session.add(record)
            await self.session.flush()
            self.session.add(
                SettlementAuditEvent(
                    store_id=self.store_id,
                    actor_id=self.actor_id,
                    action="settlement_record.create",
                    entity_type="settlement_record",
                    entity_id=record.id,
                    before_state=None,
                    after_state=record_state(record),
                )
            )
        return record

    async def update(
        self,
        record_id: int,
        *,
        company_id: int | None,
        amount: int | None,
        revision: int,
    ) -> SettlementRecord:
        async with sqlite_short_write(self.session):
            await self.recheck_access()
            record = await self.get(record_id)
            self.require_pending(record)
            self.require_revision(record, revision)
            before = record_state(record)
            if company_id is not None and company_id != record.company_id:
                company = await self.session.scalar(
                    select(SettlementCompany).where(
                        SettlementCompany.id == company_id,
                        SettlementCompany.store_id == self.store_id,
                        SettlementCompany.is_active.is_(True),
                    )
                )
                if company is None:
                    raise HTTPException(404, "当前门店的活动结算公司不存在")
                record.company_id = company.id
                record.company_name = company.name
            if amount is not None:
                record.amount = amount
            record.revision += 1
            record.updated_by = self.actor_id
            await self.session.flush()
            self.session.add(
                SettlementAuditEvent(
                    store_id=self.store_id,
                    actor_id=self.actor_id,
                    action="settlement_record.update",
                    entity_type="settlement_record",
                    entity_id=record.id,
                    before_state=before,
                    after_state=record_state(record),
                )
            )
        return record

    async def delete(self, record_id: int, *, revision: int) -> None:
        async with sqlite_short_write(self.session):
            await self.recheck_access()
            record = await self.get(record_id)
            self.require_pending(record)
            self.require_revision(record, revision)
            before = record_state(record)
            await self.session.delete(record)
            self.session.add(
                SettlementAuditEvent(
                    store_id=self.store_id,
                    actor_id=self.actor_id,
                    action="settlement_record.delete",
                    entity_type="settlement_record",
                    entity_id=record_id,
                    before_state=before,
                    after_state=None,
                )
            )
