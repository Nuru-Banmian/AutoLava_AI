"""Explicit, incremental demonstration import; never run automatically at startup."""

import asyncio
import os
import secrets
from datetime import UTC, datetime, timedelta
from random import Random
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.database import async_session_factory, sqlite_short_write
from app.core.password_work import hash_password_async
from app.models.identity import DemoImport, PermissionInitialization, Store, StoreMember, User
from app.models.ledger import (
    DailyIncomeItem,
    IncomeCategory,
    LedgerBookkeepingEvent,
    StoreDailyRecord,
)
from app.models.operations import UTC_TIMESTAMP_CONTRACT
from app.models.settlement import SettlementAuditEvent, SettlementCompany, SettlementRecord
from app.schemas.admin import StoreCreate, UserCreate
from app.scripts.initialize_permissions import INITIALIZATION_ID
from app.services.owner import owner_username
from app.services.settlement import company_state, record_state

IMPORT_ID = "job-demo"
SAMPLE_VERSION = 1


async def _already_imported(session):
    state = await session.get(PermissionInitialization, INITIALIZATION_ID, populate_existing=True)
    if state is None or not state.completed:
        raise RuntimeError("Permission initialization must complete before demo import")
    registration = await session.get(DemoImport, IMPORT_ID, populate_existing=True)
    if registration is None:
        return False
    if (
        registration.version != SAMPLE_VERSION
        or registration.store_id is None
        or registration.user_id is None
        or await session.get(Store, registration.store_id) is None
        or await session.get(User, registration.user_id) is None
    ):
        raise RuntimeError("Demo import registration is incomplete or incompatible")
    return True


async def initialize_demo(
    session, *, username="demo-guest", name="求职演示门店", password=None, days=90
):
    async with sqlite_short_write(session):
        if await _already_imported(session):
            return None
    try:
        sample_days = int(days)
    except (ValueError, TypeError):
        raise RuntimeError("Demo days must be an integer between 90 and 3660") from None
    if not 90 <= sample_days <= 3660:
        raise RuntimeError("Demo days must be an integer between 90 and 3660")
    supplied_password = password if password is not None else secrets.token_urlsafe(24)
    UserCreate(username=username, password=supplied_password, role="admin")
    name = StoreCreate(name=name, address="虚构示范街 1 号", latitude=45, longitude=9).name
    password_hash = await hash_password_async(supplied_password)
    async with sqlite_short_write(session, begin_immediate=True):
        if await _already_imported(session):
            return None
        if username == owner_username():
            raise RuntimeError("Guest username conflicts with primary administrator")
        if await session.scalar(select(User.id).where(User.username == username)) is not None:
            raise RuntimeError("Guest username already exists")
        if await session.scalar(select(Store.id).where(Store.name == name)) is not None:
            raise RuntimeError("Demo store name already exists")
        store = Store(
            name=name,
            address="虚构示范街 1 号",
            latitude=45,
            longitude=9,
            timezone="Europe/Rome",
            income_items_enabled=True,
            company_settlement_enabled=True,
            wash_count_enabled=True,
            description=(
                "虚构演示门店，位于意大利北部城市的住宅与物流混合片区，主营自助洗车和车辆护理。"
                "全部经营与天气记录均为模拟数据，不代表真实门店或天气观测。"
                "周末客流通常较高，春秋需求较旺，冬季与雨天客流较少；"
                "客户积累带来两年约18%的温和增长，日常仍有随机波动。"
                "双月设备保养及节日休息，部分日期提前收工或计数器漏报。"
                "两家虚构车队按月结算，历史账款大多已到账，近期保留待到账应收款。"
                "这些人为设定用于演示，不应作为真实经营的因果证据或预测。"
            ),
        )
        user = User(username=username, password_hash=password_hash, role="admin")
        session.add_all([store, user])
        await session.flush()
        session.add(StoreMember(store_id=store.id, user_id=user.id))
        categories = [
            IncomeCategory(
                store_id=store.id, name=label, include_in_total=included, sort_order=index
            )
            for index, (label, included) in enumerate(
                [("自助洗车", True), ("车辆护理", True), ("设备计数", False)]
            )
        ]
        session.add_all(categories)
        await session.flush()
        random = Random(279)
        today = datetime.now(ZoneInfo(store.timezone)).date()
        seasonal_demand = (0.82, 0.90, 1.05, 1.12, 1.10, 1.08, 0.98, 0.96, 1.08, 1.00, 0.86, 0.80)
        for offset in range(sample_days - 1, -1, -1):
            day = today - timedelta(days=offset)
            maintenance = day.month % 2 == 0 and day.weekday() == 0 and day.day <= 7
            closed = maintenance or (day.month, day.day) in {(1, 1), (12, 25)}
            early = not closed and day.day == 15
            weather = random.choices(
                ["晴", "多云", "小雨"],
                weights=(3, 4, 4) if day.month in {10, 11, 12, 1, 2, 3} else (6, 3, 2),
            )[0]
            growth = 1 + 0.18 * min(sample_days - 1 - offset, 730) / 730
            demand = (
                seasonal_demand[day.month - 1]
                * growth
                * (1.35 if day.weekday() >= 5 else 1)
                * (0.68 if weather == "小雨" else 0.94 if weather == "多云" else 1)
                * (0.55 if early else 1)
            )
            washes = 0 if closed else max(8, round(random.uniform(30, 44) * demand))
            care_jobs = 0 if closed else max(1, round(random.uniform(2, 5) * demand))
            amounts = [washes * 7, care_jobs * 24, washes]
            missing_count = not closed and offset % 29 == 0
            activity = (
                "虚构：设备保养休息"
                if maintenance
                else "虚构：节日休息"
                if closed
                else "虚构：员工培训，提前收工"
                if early
                else "虚构：计数器漏报，金额已清点"
                if missing_count
                else "虚构：周末车辆护理宣传"
                if day.weekday() == 5 and day.isocalendar().week % 2 == 0
                else None
            )
            occurred = (
                datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo(store.timezone))
                .replace(hour=18)
                .astimezone(UTC)
                .replace(tzinfo=None)
            )
            record = StoreDailyRecord(
                store_id=store.id,
                date=day,
                daily_revenue=sum(amounts[:2]),
                income_mode="composed",
                wash_count=None if missing_count else washes,
                is_open="休息" if closed else "提前休息" if early else "营业",
                weather=weather,
                weather_edited=True,
                activity=activity,
                created_by=user.id,
                updated_by=user.id,
                created_at=occurred,
                updated_at=occurred,
                weather_refresh_finished=True,
            )
            session.add(record)
            await session.flush()
            session.add_all(
                DailyIncomeItem(
                    record_id=record.id,
                    category_id=category.id,
                    category_name=category.name,
                    include_in_total=category.include_in_total,
                    sort_order=category.sort_order,
                    amount=amount,
                )
                for category, amount in zip(categories, amounts, strict=True)
            )
            session.add(
                LedgerBookkeepingEvent(
                    store_id=store.id,
                    record_id=record.id,
                    actor_id=user.id,
                    action="created",
                    occurred_at=occurred,
                    timestamp_contract=UTC_TIMESTAMP_CONTRACT,
                )
            )
        for index, label in enumerate(["虚构晨星车队", "虚构青禾配送"]):
            company = SettlementCompany(
                store_id=store.id,
                name=label,
                normalized_name=label,
                created_by=user.id,
                updated_by=user.id,
            )
            session.add(company)
            await session.flush()
            session.add(
                SettlementAuditEvent(
                    store_id=store.id,
                    actor_id=user.id,
                    action="settlement_company.create",
                    entity_type="settlement_company",
                    entity_id=company.id,
                    after_state=company_state(company),
                )
            )
            months = sorted(
                {(today - timedelta(days=offset)).replace(day=1) for offset in range(sample_days)}
            )
            for month in months:
                month_age = (today.year - month.year) * 12 + today.month - month.month
                confirmed = index == 0 or month_age >= 2
                invoice = SettlementRecord(
                    store_id=store.id,
                    company_id=company.id,
                    company_name=label,
                    opening_month=month,
                    amount=(
                        250 + index * 100
                        if month_age == 0
                        else 240 + index * 100 + random.randrange(0, 91, 10)
                    ),
                    status="pending",
                    created_by=user.id,
                    updated_by=user.id,
                )
                session.add(invoice)
                await session.flush()
                session.add(
                    SettlementAuditEvent(
                        store_id=store.id,
                        actor_id=user.id,
                        action="settlement_record.create",
                        entity_type="settlement_record",
                        entity_id=invoice.id,
                        after_state=record_state(invoice),
                    )
                )
                if confirmed:
                    before = record_state(invoice)
                    invoice.status = "confirmed"
                    invoice.revision += 1
                    session.add(
                        SettlementAuditEvent(
                            store_id=store.id,
                            actor_id=user.id,
                            action="settlement_record.confirm",
                            entity_type="settlement_record",
                            entity_id=invoice.id,
                            before_state=before,
                            after_state=record_state(invoice),
                        )
                    )
        session.add(
            DemoImport(id=IMPORT_ID, version=SAMPLE_VERSION, store_id=store.id, user_id=user.id)
        )
    return username, supplied_password


async def run():
    async with async_session_factory() as session:
        return await initialize_demo(
            session,
            username=os.environ.get("AUTOLAVA_DEMO_USERNAME", "demo-guest"),
            name=os.environ.get("AUTOLAVA_DEMO_STORE_NAME", "求职演示门店"),
            password=os.environ.get("AUTOLAVA_DEMO_PASSWORD"),
            days=os.environ.get("AUTOLAVA_DEMO_DAYS", "90"),
        )


def main():
    try:
        credentials = asyncio.run(run())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
    except Exception:
        # Suppress SQL parameters and validation payloads that may contain secrets.
        raise SystemExit(
            "Demo initialization failed; check migration, permission initialization and identity conflicts."
        ) from None
    if credentials is None:
        print("Demo already initialized; unchanged.")
    else:
        print(f"Demo initialized. Username: {credentials[0]}\nPassword: {credentials[1]}")


if __name__ == "__main__":
    main()
