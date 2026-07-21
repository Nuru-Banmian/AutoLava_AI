from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import sqlite_short_write
from app.models.settlement import SettlementAuditEvent, SettlementCompany, SettlementRecord
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
