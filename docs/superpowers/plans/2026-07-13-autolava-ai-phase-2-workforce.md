# AutoLava AI Phase 2 Workforce and Payroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add store-scoped worker management, integer-hour entry, deterministic wage calculation, versioned monthly payroll snapshots, stale-settlement warnings, audit history, Excel export, and responsive desktop/mobile workflows.

**Architecture:** Extend the Phase 1 FastAPI and React applications rather than creating a separate payroll service. Keep wage calculation as a pure Decimal-based domain function, place time-entry and settlement writes in transaction-scoped services, and snapshot all payroll inputs so later edits never rewrite historical settlements. The browser uses one monthly data contract rendered as a desktop matrix or mobile day cards.

**Tech Stack:** Existing Phase 1 stack plus SQLAlchemy workforce models, openpyxl workbook generation, React Hook Form, Vitest, and Playwright.

## Global Constraints

- Phase 1 is complete and its auth, store-access, audit, export, query, CI, and deployment contracts remain authoritative.
- Workers are store-scoped and are disabled rather than physically deleted.
- `standard_work_hours` is an integer from 1 through 24.
- Worker time supports only `未填写`, `0 小时`, and integer values from 1 through 24; it stores no clock-in/out values and no notes.
- `worker_id + work_date` is unique.
- Daily wage equals `min(hours, standard_work_hours) / standard_work_hours * daily_full_wage`; hours beyond the standard do not increase pay.
- A monthly payroll stores the standard-hours, worker-name, and full-day-wage snapshots used for its calculation.
- Editing settled time does not change an existing snapshot; it marks the active settlement as inconsistent and offers regeneration.
- Regeneration marks the previous active payroll `superseded` and retains it.
- All time and payroll mutations are audited; users may operate only on authorized stores.
- The workers module remains independent from weather, ledger revenue, and AI.

---

## File Structure

```text
backend/
├── alembic/versions/0002_workforce.py
├── app/models/workforce.py
├── app/schemas/workforce.py
├── app/services/{workforce,payroll,workforce_export}.py
├── app/api/routes/workers.py
└── tests/
    ├── services/{test_workforce,test_payroll,test_workforce_export}.py
    └── api/test_workers.py
frontend/
├── src/api/types.ts
├── src/components/workers/{WorkerToolbar,DesktopTimeGrid,MobileDayCards,PayrollSummary}.tsx
├── src/pages/WorkersPage.tsx
├── src/pages/WorkersPage.test.tsx
└── tests/workers-responsive.spec.ts
```

## Shared interfaces

```python
calculate_day_wage(hours: int | None, standard_hours: int, full_day_wage: Decimal) -> Decimal
summarize_worker(entries: list[int | None], standard_hours: int, full_day_wage: Decimal) -> WorkerSummary
WorkforceService.replace_day(store_id: int, work_date: date, entries: list[TimeEntryInput], actor: User) -> list[WorkerTimeRecord]
PayrollService.generate(store_id: int, month: date, actor: User) -> WorkerPayroll
PayrollService.status(store_id: int, month: date) -> PayrollStatus
```

```text
GET    /api/workers/{store_id}?include_inactive=
POST   /api/workers/{store_id}
PATCH  /api/workers/{store_id}/{worker_id}
GET    /api/workers/{store_id}/month/{YYYY-MM}
PUT    /api/workers/{store_id}/day/{YYYY-MM-DD}
POST   /api/workers/{store_id}/day/{YYYY-MM-DD}/copy-previous
GET    /api/workers/{store_id}/payroll/{YYYY-MM}/status
POST   /api/workers/{store_id}/payroll/{YYYY-MM}
GET    /api/workers/{store_id}/payroll/{payroll_id}
GET    /api/workers/{store_id}/export.xlsx?month=YYYY-MM
```

### Task 1: Add workforce and payroll persistence

**Files:**
- Create: `backend/app/models/workforce.py`
- Create: `backend/alembic/versions/0002_workforce.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_workforce_schema.py`

**Interfaces:**
- Consumes: `Store`, `User`, and the Phase 1 SQLAlchemy base.
- Produces: `Worker`, `WorkerTimeRecord`, `WorkerPayroll`, and `WorkerPayrollItem` models with the spec's foreign keys, checks, and snapshots.

- [ ] **Step 1: Write failing metadata and constraint tests**

```python
# backend/tests/test_workforce_schema.py
from app.models.base import Base
import app.models.workforce  # noqa: F401


def test_workforce_tables_are_registered() -> None:
    assert {"workers", "worker_time_records", "worker_payrolls", "worker_payroll_items"} <= set(Base.metadata.tables)


def test_time_record_is_unique_per_worker_day() -> None:
    names = {constraint.name for constraint in Base.metadata.tables["worker_time_records"].constraints}
    assert "uq_worker_time_records_worker_date" in names


def test_hours_and_status_have_database_checks() -> None:
    time_checks = {constraint.name for constraint in Base.metadata.tables["worker_time_records"].constraints}
    payroll_checks = {constraint.name for constraint in Base.metadata.tables["worker_payrolls"].constraints}
    assert "ck_worker_time_records_hours" in time_checks
    assert "ck_worker_payrolls_status" in payroll_checks
```

- [ ] **Step 2: Run the schema tests and verify the model import fails**

Run: `cd backend && pytest tests/test_workforce_schema.py -q`

Expected: FAIL with `ModuleNotFoundError: app.models.workforce`.

- [ ] **Step 3: Define all workforce models**

```python
# backend/app/models/workforce.py
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Worker(Base):
    __tablename__ = "workers"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    name: Mapped[str] = mapped_column(String(120))
    daily_full_wage: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class WorkerTimeRecord(Base):
    __tablename__ = "worker_time_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"))
    work_date: Mapped[date] = mapped_column(Date)
    hours: Mapped[int | None]
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("worker_id", "work_date", name="uq_worker_time_records_worker_date"),
        CheckConstraint("hours is null or hours between 0 and 24", name="hours"),
    )


class WorkerPayroll(Base):
    __tablename__ = "worker_payrolls"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    month: Mapped[date] = mapped_column(Date)
    standard_work_hours: Mapped[int]
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    items: Mapped[list["WorkerPayrollItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (CheckConstraint("status in ('active','superseded')", name="status"),)


class WorkerPayrollItem(Base):
    __tablename__ = "worker_payroll_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    payroll_id: Mapped[int] = mapped_column(ForeignKey("worker_payrolls.id", ondelete="CASCADE"))
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"))
    worker_name_snapshot: Mapped[str] = mapped_column(String(120))
    total_hours: Mapped[int]
    work_days: Mapped[int]
    standard_days: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    daily_full_wage_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

- [ ] **Step 4: Generate/apply migration and rerun schema tests**

Run: `cd backend && alembic revision --autogenerate -m "workforce and payroll" && alembic upgrade head && pytest tests/test_workforce_schema.py -q`

Expected: migration adds four tables without altering Phase 1 tables and all schema tests pass. Rename the generated file to `0002_workforce.py` while retaining its revision identifiers.

- [ ] **Step 5: Commit workforce persistence**

```bash
git add backend/app/models backend/alembic backend/tests/test_workforce_schema.py
git commit -m "feat: add workforce and payroll schema"
```

### Task 2: Implement deterministic wage calculations

**Files:**
- Create: `backend/app/services/payroll.py`
- Create: `backend/tests/services/test_payroll.py`

**Interfaces:**
- Consumes: integer/empty hours, store standard hours, worker full-day wage.
- Produces: `WorkerSummary(total_hours: int, work_days: int, standard_days: Decimal, amount: Decimal)`, with money rounded to cents using `ROUND_HALF_UP` only after summing individually capped days.

- [ ] **Step 1: Write the wage boundary table as failing tests**

```python
# backend/tests/services/test_payroll.py
from decimal import Decimal

import pytest

from app.services.payroll import calculate_day_wage, summarize_worker


@pytest.mark.parametrize(("hours", "expected"), [
    (None, "0.00"), (0, "0.00"), (1, "10.00"), (4, "40.00"),
    (8, "80.00"), (12, "80.00"), (24, "80.00"),
])
def test_daily_wage_is_prorated_and_capped(hours, expected) -> None:
    assert calculate_day_wage(hours, 8, Decimal("80.00")) == Decimal(expected)


def test_month_summary_distinguishes_zero_from_work_day() -> None:
    result = summarize_worker([None, 0, 4, 8, 12], 8, Decimal("80.00"))
    assert result.total_hours == 24
    assert result.work_days == 3
    assert result.standard_days == Decimal("3.00")
    assert result.amount == Decimal("200.00")


@pytest.mark.parametrize("standard_hours", [0, 25])
def test_invalid_standard_hours_are_rejected(standard_hours) -> None:
    with pytest.raises(ValueError, match="standard_hours must be between 1 and 24"):
        calculate_day_wage(8, standard_hours, Decimal("80"))
```

- [ ] **Step 2: Run tests and verify the calculation module is missing**

Run: `cd backend && pytest tests/services/test_payroll.py -q`

Expected: FAIL importing `app.services.payroll`.

- [ ] **Step 3: Implement pure Decimal calculations**

```python
# backend/app/services/payroll.py
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


@dataclass(frozen=True)
class WorkerSummary:
    total_hours: int
    work_days: int
    standard_days: Decimal
    amount: Decimal


def calculate_day_wage(hours: int | None, standard_hours: int,
                       full_day_wage: Decimal) -> Decimal:
    if not 1 <= standard_hours <= 24:
        raise ValueError("standard_hours must be between 1 and 24")
    if hours is None:
        return Decimal("0.00")
    if not 0 <= hours <= 24:
        raise ValueError("hours must be between 0 and 24")
    capped = min(hours, standard_hours)
    return Decimal(capped) / Decimal(standard_hours) * full_day_wage


def summarize_worker(entries: list[int | None], standard_hours: int,
                     full_day_wage: Decimal) -> WorkerSummary:
    total_hours = sum(hours or 0 for hours in entries)
    work_days = sum(hours is not None and hours > 0 for hours in entries)
    amount = sum(
        (calculate_day_wage(hours, standard_hours, full_day_wage) for hours in entries),
        start=Decimal("0"),
    ).quantize(CENT, rounding=ROUND_HALF_UP)
    standard_days = (Decimal(total_hours) / Decimal(standard_hours)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )
    return WorkerSummary(total_hours, work_days, standard_days, amount)
```

- [ ] **Step 4: Run wage tests and full backend regression suite**

Run: `cd backend && pytest tests/services/test_payroll.py -q && pytest -q`

Expected: all boundary tests and all Phase 1 regression tests pass.

- [ ] **Step 5: Commit the calculation domain**

```bash
git add backend/app/services/payroll.py backend/tests/services/test_payroll.py
git commit -m "feat: add deterministic wage calculations"
```

### Task 3: Add worker configuration and audited monthly time-entry APIs

**Files:**
- Create: `backend/app/schemas/workforce.py`
- Create: `backend/app/services/workforce.py`
- Create: `backend/app/api/routes/workers.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/services/audit.py`
- Create: `backend/tests/services/test_workforce.py`
- Create: `backend/tests/api/test_workers.py`

**Interfaces:**
- Consumes: `require_store_access`, `StoreSetting`, workforce models, and Phase 1 `AuditLog`.
- Produces: active/inactive worker configuration, monthly grid response, atomic day replacement, previous-day copy, and `worker_time` audit entries.

- [ ] **Step 1: Write failing store isolation, null/zero, copy, and audit tests**

```python
# backend/tests/api/test_workers.py
async def test_day_replace_preserves_null_and_zero(auth_client, assigned_store, two_workers) -> None:
    response = await auth_client.put(f"/api/workers/{assigned_store.id}/day/2026-07-13", json={
        "entries": [
            {"worker_id": two_workers[0].id, "hours": None},
            {"worker_id": two_workers[1].id, "hours": 0},
        ],
    })
    assert response.status_code == 200
    by_worker = {entry["worker_id"]: entry["hours"] for entry in response.json()["entries"]}
    assert by_worker == {two_workers[0].id: None, two_workers[1].id: 0}


async def test_copy_previous_overwrites_only_after_confirmation(auth_client, assigned_store, time_grid) -> None:
    path = f"/api/workers/{assigned_store.id}/day/2026-07-14/copy-previous"
    response = await auth_client.post(path)
    assert response.status_code == 409
    response = await auth_client.post(path + "?overwrite=true")
    assert response.status_code == 200
    assert response.json()["source_date"] == "2026-07-13"


async def test_worker_from_other_store_is_rejected(auth_client, assigned_store, foreign_worker) -> None:
    response = await auth_client.put(f"/api/workers/{assigned_store.id}/day/2026-07-13", json={
        "entries": [{"worker_id": foreign_worker.id, "hours": 8}],
    })
    assert response.status_code == 422
```

- [ ] **Step 2: Run worker API tests and verify routes are missing**

Run: `cd backend && pytest tests/services/test_workforce.py tests/api/test_workers.py -q`

Expected: FAIL because workforce service and routes do not exist.

- [ ] **Step 3: Implement atomic day replacement and audit snapshots**

```python
# backend/app/services/workforce.py
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.identity import User
from app.models.workforce import Worker, WorkerTimeRecord


class WorkforceService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def replace_day(self, *, store_id: int, work_date: date,
                          entries: list[dict], actor: User) -> list[WorkerTimeRecord]:
        if len({entry["worker_id"] for entry in entries}) != len(entries):
            raise HTTPException(422, "Each worker may appear only once")
        workers = (await self.session.scalars(select(Worker).where(
            Worker.store_id == store_id,
            Worker.id.in_([entry["worker_id"] for entry in entries]),
        ))).all()
        if len(workers) != len(entries):
            raise HTTPException(422, "Worker does not belong to this store")
        existing = (await self.session.scalars(select(WorkerTimeRecord).where(
            WorkerTimeRecord.store_id == store_id,
            WorkerTimeRecord.work_date == work_date,
        ))).all()
        by_worker = {record.worker_id: record for record in existing}
        before = [{"worker_id": record.worker_id, "hours": record.hours} for record in existing]
        result = []
        for entry in entries:
            hours = entry["hours"]
            if hours is not None and not 0 <= hours <= 24:
                raise HTTPException(422, "Hours must be null or an integer from 0 through 24")
            record = by_worker.get(entry["worker_id"])
            if record is None:
                record = WorkerTimeRecord(
                    store_id=store_id, worker_id=entry["worker_id"], work_date=work_date,
                    hours=hours, created_by=actor.id, updated_by=actor.id,
                )
                self.session.add(record)
            else:
                record.hours = hours
                record.updated_by = actor.id
            result.append(record)
        await self.session.flush()
        after = [{"worker_id": record.worker_id, "hours": record.hours} for record in result]
        self.session.add(AuditLog(
            operation_domain="worker_time", store_id=store_id, record_id=None,
            record_date=work_date, operation_type="update" if existing else "create",
            operation_source="manual", operator_user_id=actor.id,
            before_json={"entries": before}, after_json={"entries": after},
            description=f"Worker time for {work_date.isoformat()}",
            requires_approval=False, approved=True,
        ))
        await self.session.commit()
        return result
```

- [ ] **Step 4: Add routes, monthly summaries, and previous-day copy**

`GET /month/{month}` returns every calendar date, every active worker ordered by `sort_order,id`, each `hours` value including null, the current setting, calculated worker summaries, total payroll, and active-payroll status. `POST/PATCH` worker routes verify the worker belongs to the path store; patch supports name, wage, active flag, and sort order. `PATCH /settings` accepts only integers 1..24. Worker create/patch and setting changes write complete before/after configuration audits without exposing unrelated stores. Copy uses the immediately preceding calendar day, returns 404 if it has no entries, returns 409 when target entries exist without `overwrite=true`, and writes one audit entry for the copied target day.

Run: `cd backend && pytest tests/services/test_workforce.py tests/api/test_workers.py -q`

Expected: worker configuration, settings validation, store isolation, null/zero distinction, atomic replacement, copying, summaries, and audit tests pass.

- [ ] **Step 5: Commit workforce APIs**

```bash
git add backend/app/schemas/workforce.py backend/app/services/workforce.py backend/app/api/routes/workers.py backend/app/api/router.py backend/app/services/audit.py backend/tests
git commit -m "feat: add audited workforce time entry APIs"
```

### Task 4: Generate immutable payroll snapshots and stale-settlement status

**Files:**
- Modify: `backend/app/services/payroll.py`
- Modify: `backend/app/api/routes/workers.py`
- Modify: `backend/app/schemas/workforce.py`
- Create: `backend/tests/services/test_payroll_generation.py`
- Modify: `backend/tests/api/test_workers.py`

**Interfaces:**
- Consumes: store setting, workers, monthly time records, wage pure functions, and audit log.
- Produces: one active payroll per store/month under the service transaction, retained superseded payrolls, and `PayrollStatus(exists, is_stale, active_payroll_id, differences)`.

- [ ] **Step 1: Write failing snapshot/regeneration/staleness tests**

```python
# backend/tests/services/test_payroll_generation.py
async def test_payroll_snapshots_names_wages_and_standard_hours(payroll_service, payroll_month) -> None:
    payroll = await payroll_service.generate(payroll_month.store_id, payroll_month.month, payroll_month.actor)
    assert payroll.standard_work_hours == 8
    assert payroll.status == "active"
    assert payroll.items[0].worker_name_snapshot == "Mario"
    assert payroll.items[0].daily_full_wage_snapshot == Decimal("80.00")
    assert payroll.total_amount == sum(item.amount for item in payroll.items)


async def test_time_change_marks_snapshot_stale_without_mutating_it(payroll_service, payroll_month) -> None:
    payroll = await payroll_service.generate(payroll_month.store_id, payroll_month.month, payroll_month.actor)
    original = payroll.total_amount
    await payroll_month.change_hours(worker="Mario", day=3, hours=0)
    status = await payroll_service.status(payroll_month.store_id, payroll_month.month)
    assert status.is_stale is True
    assert status.differences[0]["worker_name"] == "Mario"
    assert payroll.total_amount == original


async def test_regeneration_supersedes_previous_snapshot(payroll_service, payroll_month) -> None:
    old = await payroll_service.generate(payroll_month.store_id, payroll_month.month, payroll_month.actor)
    new = await payroll_service.generate(payroll_month.store_id, payroll_month.month, payroll_month.actor)
    assert old.id != new.id
    assert await payroll_month.refresh(old).status == "superseded"
    assert new.status == "active"
```

- [ ] **Step 2: Run generation tests and verify missing service methods**

Run: `cd backend && pytest tests/services/test_payroll_generation.py -q`

Expected: FAIL because `PayrollService.generate` and `status` are absent.

- [ ] **Step 3: Implement snapshot generation in one transaction**

```python
# backend/app/services/payroll.py (add below pure functions)
def payroll_snapshot(payroll: WorkerPayroll) -> dict:
    return {
        "id": payroll.id,
        "store_id": payroll.store_id,
        "month": payroll.month.isoformat(),
        "standard_work_hours": payroll.standard_work_hours,
        "total_amount": str(payroll.total_amount),
        "status": payroll.status,
        "items": [
            {
                "worker_id": item.worker_id,
                "worker_name_snapshot": item.worker_name_snapshot,
                "total_hours": item.total_hours,
                "work_days": item.work_days,
                "standard_days": str(item.standard_days),
                "daily_full_wage_snapshot": str(item.daily_full_wage_snapshot),
                "amount": str(item.amount),
            }
            for item in payroll.items
        ],
    }


def payroll_audit(payroll: WorkerPayroll, actor_id: int,
                  previous_snapshot: dict | None) -> AuditLog:
    return AuditLog(
        operation_domain="payroll", store_id=payroll.store_id, record_id=payroll.id,
        record_date=payroll.month,
        operation_type="create" if previous_snapshot is None else "update",
        operation_source="manual", operator_user_id=actor_id,
        before_json=previous_snapshot, after_json=payroll_snapshot(payroll),
        description=f"Payroll settlement for {payroll.month:%Y-%m}",
        requires_approval=False, approved=True,
    )


class PayrollService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def generate(self, store_id: int, month: date, actor: User) -> WorkerPayroll:
        month = month.replace(day=1)
        setting = await self.session.get(StoreSetting, store_id, with_for_update=True)
        workers = (await self.session.scalars(select(Worker).where(Worker.store_id == store_id))).all()
        records = (await self.session.scalars(select(WorkerTimeRecord).where(
            WorkerTimeRecord.store_id == store_id,
            WorkerTimeRecord.work_date >= month,
            WorkerTimeRecord.work_date < next_month(month),
        ))).all()
        entries: dict[int, list[int | None]] = defaultdict(list)
        for record in records:
            entries[record.worker_id].append(record.hours)
        active = await self.session.scalar(select(WorkerPayroll).where(
            WorkerPayroll.store_id == store_id, WorkerPayroll.month == month,
            WorkerPayroll.status == "active",
        ).with_for_update())
        previous_snapshot = None if active is None else payroll_snapshot(active)
        if active is not None:
            active.status = "superseded"
        payroll = WorkerPayroll(
            store_id=store_id, month=month, standard_work_hours=setting.standard_work_hours,
            total_amount=Decimal("0.00"), status="active", created_by=actor.id,
        )
        payroll.items = []
        for worker in workers:
            summary = summarize_worker(entries[worker.id], setting.standard_work_hours, worker.daily_full_wage)
            payroll.items.append(WorkerPayrollItem(
                worker_id=worker.id, worker_name_snapshot=worker.name,
                total_hours=summary.total_hours, work_days=summary.work_days,
                standard_days=summary.standard_days,
                daily_full_wage_snapshot=worker.daily_full_wage, amount=summary.amount,
            ))
        payroll.total_amount = sum((item.amount for item in payroll.items), Decimal("0.00"))
        self.session.add(payroll)
        await self.session.flush()
        self.session.add(payroll_audit(payroll, actor.id, previous_snapshot))
        await self.session.commit()
        return payroll
```

- [ ] **Step 4: Implement status comparison and authorized endpoints**

`status()` recalculates the current month from current hours, current worker wages, and the current store standard hours, then compares the store-hours setting and each item's `total_hours`, `work_days`, `standard_days`, wage snapshot, and amount against the active snapshot. It returns structured differences without altering a row. `POST /payroll/{month}` generates/regenerates after confirmation; `GET /payroll/{month}/status` and `GET /payroll/{payroll_id}` enforce path-store ownership and include superseded snapshots only when addressed by id.

Run: `cd backend && pytest tests/services/test_payroll.py tests/services/test_payroll_generation.py tests/api/test_workers.py -q`

Expected: snapshot, staleness, retained superseded version, regenerated active version, audit, and store-isolation tests pass.

- [ ] **Step 5: Commit payroll snapshots**

```bash
git add backend/app/services/payroll.py backend/app/api/routes/workers.py backend/app/schemas/workforce.py backend/tests
git commit -m "feat: add versioned monthly payroll settlements"
```

### Task 5: Add workforce Excel export and responsive workers UI

**Files:**
- Create: `backend/app/services/workforce_export.py`
- Modify: `backend/app/api/routes/workers.py`
- Create: `backend/tests/services/test_workforce_export.py`
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/components/workers/WorkerToolbar.tsx`
- Create: `frontend/src/components/workers/DesktopTimeGrid.tsx`
- Create: `frontend/src/components/workers/MobileDayCards.tsx`
- Create: `frontend/src/components/workers/PayrollSummary.tsx`
- Create: `frontend/src/pages/WorkersPage.tsx`
- Create: `frontend/src/pages/WorkersPage.test.tsx`
- Create: `frontend/tests/workers-responsive.spec.ts`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/layouts/AppShell.tsx`

**Interfaces:**
- Consumes: monthly workforce API and payroll status.
- Produces: one workbook with daily grid and monthly summary sheets; one React page with desktop matrix and mobile day-card renderers over the same query/mutations.

- [ ] **Step 1: Write failing workbook and responsive component tests**

```python
# backend/tests/services/test_workforce_export.py
def test_workbook_contains_grid_and_summary(workforce_export_fixture) -> None:
    workbook = load_workbook(BytesIO(build_workforce_workbook(workforce_export_fixture)))
    assert workbook.sheetnames == ["工时", "月度汇总"]
    assert list(workbook["工时"].values)[0] == ("日期", "Mario", "Luigi")
    assert list(workbook["月度汇总"].values)[0] == (
        "工人", "总小时", "上班天数", "折合标准工作日", "满标准日工资", "本月工资",
    )
```

```tsx
// frontend/src/pages/WorkersPage.test.tsx
it("keeps unfilled distinct from zero and displays stale payroll warning", async () => {
  renderWorkersPage(monthFixture({ hours: [null, 0], payroll: { exists: true, is_stale: true } }));
  expect(await screen.findByLabelText("Mario 7月1日")).toHaveValue("unfilled");
  expect(screen.getByLabelText("Luigi 7月1日")).toHaveValue("0");
  expect(screen.getByText("工时已变化，需要重新生成结算")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run export/UI tests and verify missing modules**

Run: `cd backend && pytest tests/services/test_workforce_export.py -q; cd ../frontend && npm test -- WorkersPage`

Expected: both commands fail because export and workers-page modules are absent.

- [ ] **Step 3: Implement the exact two-sheet workbook**

```python
# backend/app/services/workforce_export.py
from io import BytesIO
from openpyxl import Workbook


def build_workforce_workbook(month: dict) -> bytes:
    workbook = Workbook()
    grid = workbook.active
    grid.title = "工时"
    grid.append(["日期", *[worker["name"] for worker in month["workers"]]])
    for day in month["days"]:
        by_worker = {entry["worker_id"]: entry["hours"] for entry in day["entries"]}
        grid.append([day["date"], *[by_worker.get(worker["id"]) for worker in month["workers"]]])
    summary = workbook.create_sheet("月度汇总")
    summary.append(["工人", "总小时", "上班天数", "折合标准工作日", "满标准日工资", "本月工资"])
    for item in month["summaries"]:
        summary.append([item["worker_name"], item["total_hours"], item["work_days"],
                        float(item["standard_days"]), float(item["daily_full_wage"]), float(item["amount"])])
    summary.append(["合计", None, None, None, None, float(month["total_amount"])])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
```

- [ ] **Step 4: Implement both responsive renderers and verify full workflows**

`DesktopTimeGrid` renders one row per day and one column per worker above 768px. `MobileDayCards` renders one card per day below 768px. Both use the identical values `unfilled`, `0`, ... `24`; mobile uses a native `<select>` so iOS/Android presents its scroll wheel, while desktop uses the scrollable shadcn Select list. Both submit a whole day atomically and expose copy-previous. Toolbar manages store, month, workers, standard hours, and wages. Payroll summary shows recalculated live totals, active snapshot details, staleness differences, confirmation before generation/regeneration, and export.

Run: `cd backend && pytest -q; cd ../frontend && npm test && npx playwright test tests/workers-responsive.spec.ts && npm run build`

Expected: backend regression passes; UI tests pass; Playwright verifies matrix layout at 1280px, day cards without horizontal overflow at 390px, scroll-select values, historical month editing, copy confirmation, stale warning, regeneration, and export download.

- [ ] **Step 5: Commit the complete workforce module**

```bash
git add backend frontend
git commit -m "feat: add workforce export and responsive payroll UI"
```

### Task 6: Verify the Phase 2 release and deployment migration

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`
- Create: `backend/tests/api/test_workforce_journey.py`

**Interfaces:**
- Consumes: the complete Phase 2 API/UI and existing two-container deployment.
- Produces: a repeatable release gate that upgrades an existing Phase 1 database and exercises a complete settled-month lifecycle.

- [ ] **Step 1: Add a failing end-to-end API lifecycle test**

```python
# backend/tests/api/test_workforce_journey.py
async def test_settled_month_lifecycle(auth_client, assigned_store) -> None:
    worker = (await auth_client.post(f"/api/workers/{assigned_store.id}", json={
        "name": "Mario", "daily_full_wage": "80.00", "sort_order": 0,
    })).json()
    await auth_client.put(f"/api/workers/{assigned_store.id}/day/2026-07-01", json={
        "entries": [{"worker_id": worker["id"], "hours": 8}],
    })
    payroll = (await auth_client.post(f"/api/workers/{assigned_store.id}/payroll/2026-07")).json()
    assert payroll["total_amount"] == "80.00"
    await auth_client.put(f"/api/workers/{assigned_store.id}/day/2026-07-01", json={
        "entries": [{"worker_id": worker["id"], "hours": 4}],
    })
    status = (await auth_client.get(f"/api/workers/{assigned_store.id}/payroll/2026-07/status")).json()
    assert status["is_stale"] is True
    replacement = (await auth_client.post(f"/api/workers/{assigned_store.id}/payroll/2026-07?confirm=true")).json()
    assert replacement["total_amount"] == "40.00"
    assert replacement["id"] != payroll["id"]
```

- [ ] **Step 2: Run the lifecycle test and fix any contract mismatch**

Run: `cd backend && pytest tests/api/test_workforce_journey.py -q`

Expected: PASS after route schemas and service return types match the shared interfaces exactly.

- [ ] **Step 3: Verify forward and backward migration on a disposable MySQL database**

Run: `cd backend && alembic upgrade 0001 && alembic upgrade head && alembic downgrade 0001 && alembic upgrade head`

Expected: workforce tables are created, removed without affecting Phase 1 tables, and recreated successfully.

- [ ] **Step 4: Run the release gate and document operations**

Update README with worker setup, standard-hours semantics, null-versus-zero semantics, payroll regeneration, export, migration, and rollback commands.

Run: `cd backend && ruff check . && pytest --cov=app; cd ../frontend && npm test && npm run build && npx playwright test; cd .. && docker compose build`

Expected: lint, backend, frontend, browser, migration, and image-build checks pass.

- [ ] **Step 5: Commit Phase 2 release verification**

```bash
git add README.md .github/workflows/ci.yml backend/tests/api/test_workforce_journey.py
git commit -m "test: verify workforce and payroll release"
```

## Phase 2 acceptance checklist

- Null time and explicit zero remain distinguishable through database, API, UI, audit, and export.
- Hours accept integers 0 through 24 and reject decimals or values outside that range.
- Wage calculation caps each day at the store's standard hours.
- Payroll snapshots keep names, wages, standard hours, totals, and prior versions unchanged.
- Editing settled time yields structured staleness differences and regeneration keeps the old snapshot as `superseded`.
- Desktop uses the monthly matrix; mobile uses day cards; both submit the same atomic day contract.
- Workers and payroll data never cross store-access boundaries and never depend on weather, revenue, or AI.
