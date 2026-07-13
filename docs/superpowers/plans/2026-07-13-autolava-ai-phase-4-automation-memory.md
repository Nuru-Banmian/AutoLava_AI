# AutoLava AI Phase 4 Automation and Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete reliable store-local automation, retry missing weather without harming ledger entry, extract conservative per-store memories, enrich cached briefings, and expose actionable task/alert operations to administrators.

**Architecture:** Keep APScheduler inside the single FastAPI process as required, but make every scheduled unit idempotent through stable run keys and database transactions. A deterministic memory engine recomputes weather, weekday, and repeated-activity patterns from authorized store data, stores qualitative direction/confidence, and exposes only confidence 50 or higher. Briefing generation always has a deterministic fallback; model polishing is optional and cannot block cards or scheduled progress.

**Tech Stack:** Existing Phase 1-3 stack plus APScheduler cron/interval triggers, SQLAlchemy task locking, deterministic Decimal statistics, React Query administrator views, pytest time control, and Playwright.

## Global Constraints

- Phases 1 through 3 are complete; the scheduler remains in one FastAPI backend process until a later multi-instance design.
- Each active store runs its daily workflow at 04:00 in that store's configured time zone.
- Daily order is: today's weather, tomorrow's weather, yesterday's missing weather, new-data scan, memory refresh, yesterday card, today card, tomorrow card, missing-yesterday check, task log.
- Weather compensation never blocks ledger entry and never overwrites user-edited `weather`; it may fill `weather_auto`, code, temperatures, and precipitation.
- Three failed weather attempts create one unresolved administrator alert; subsequent identical failures update/reuse that alert rather than duplicate it.
- Memories are independent by store and limited to `weather`, `weekday`, and `activity`.
- A pattern seen once is never stored as a memory; repeated-activity patterns require at least three occurrences and weather/weekday patterns require at least four.
- Memory descriptions are qualitative and never contain a predicted percentage.
- Confidence is an integer from 0 through 100; confidence below 50 is never proactively returned to users.
- Scheduled jobs and task retries are observable through `scheduled_task_logs`; administrator alerts are resolvable but not physically deleted.
- Homepage card reads remain cache-only and do not wait for weather, memory, or LLM calls.

---

## File Structure

```text
backend/
├── alembic/versions/0004_automation_memory.py
├── app/models/memory.py
├── app/services/{memory,scheduler,daily_workflow,weather_compensation,alerts}.py
├── app/api/routes/{dashboard,admin}.py
└── tests/
    ├── services/{test_memory,test_scheduler,test_daily_workflow,test_weather_compensation,test_memory_briefing}.py
    └── api/{test_admin_operations,test_dashboard_memory}.py
frontend/
├── src/components/admin/{AlertList,TaskLogList}.tsx
├── src/components/BriefingCards.tsx
├── src/pages/{Admin,Home}Page.tsx
├── src/pages/AdminPage.test.tsx
└── tests/automation-observability.spec.ts
```

## Shared interfaces

```python
MemoryEngine.refresh(store_id: int, local_date: date) -> list[AgentMemory]
visible_memories(store_id: int, memory_types: set[str] | None = None) -> list[AgentMemory]
DailyWorkflow.run(store_id: int, local_date: date) -> DailyRunResult
WeatherCompensation.run(limit: int = 50) -> CompensationResult
AlertService.upsert(store_id, alert_type, level, message_key, message) -> SystemAlert
run_once(run_key: str, task_type: str, store_id: int | None, operation: Callable) -> ScheduledTaskLog
```

### Task 1: Add memory persistence and idempotent task keys

**Files:**
- Create: `backend/app/models/memory.py`
- Modify: `backend/app/models/operations.py`
- Create: `backend/alembic/versions/0004_automation_memory.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_automation_schema.py`

**Interfaces:**
- Consumes: Phase 1 `Store`, `ScheduledTaskLog`, and ledger `scanned` flag.
- Produces: `AgentMemory` unique by store/type/pattern and nullable unique `ScheduledTaskLog.run_key` used for idempotent daily jobs and persistent weather retries.

- [ ] **Step 1: Write failing schema/constraint tests**

```python
# backend/tests/test_automation_schema.py
from app.models.base import Base
import app.models.memory  # noqa: F401
import app.models.operations  # noqa: F401


def test_memory_table_and_pattern_identity_exist() -> None:
    table = Base.metadata.tables["agent_memory"]
    assert {"store_id", "memory_type", "pattern", "impact_direction", "description",
            "confidence", "last_seen_at"} <= set(table.c.keys())
    assert "uq_agent_memory_store_type_pattern" in {constraint.name for constraint in table.constraints}


def test_scheduled_logs_have_unique_run_key() -> None:
    table = Base.metadata.tables["scheduled_task_logs"]
    assert "run_key" in table.c
    assert table.c.run_key.unique is True
```

- [ ] **Step 2: Run schema tests and verify missing model/column**

Run: `cd backend && pytest tests/test_automation_schema.py -q`

Expected: FAIL importing `app.models.memory` and finding `run_key`.

- [ ] **Step 3: Define memory model and task-log key**

```python
# backend/app/models/memory.py
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentMemory(Base):
    __tablename__ = "agent_memory"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    memory_type: Mapped[str] = mapped_column(String(20))
    pattern: Mapped[str] = mapped_column(String(255))
    impact_direction: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    confidence: Mapped[int]
    last_seen_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("store_id", "memory_type", "pattern", name="uq_agent_memory_store_type_pattern"),
        CheckConstraint("memory_type in ('weather','weekday','activity')", name="type"),
        CheckConstraint("impact_direction in ('上升','下降','无明显影响')", name="direction"),
        CheckConstraint("confidence between 0 and 100", name="confidence"),
    )
```

Add `run_key: Mapped[str | None] = mapped_column(String(255), unique=True)` to `ScheduledTaskLog`. Existing Phase 1 rows remain null and therefore do not collide in MySQL.

- [ ] **Step 4: Generate/apply the migration and verify upgrade/downgrade**

Run: `cd backend && alembic revision --autogenerate -m "automation memory" && alembic upgrade head && pytest tests/test_automation_schema.py -q && alembic downgrade 0003 && alembic upgrade head`

Expected: `agent_memory` and the nullable unique `run_key` are added, schema tests pass, and the migration round-trip preserves prior tables/data. Rename the generated revision file to `0004_automation_memory.py` while retaining the revision chain.

- [ ] **Step 5: Commit automation persistence**

```bash
git add backend/app/models backend/alembic backend/tests/test_automation_schema.py
git commit -m "feat: add automation memory persistence"
```

### Task 2: Implement conservative deterministic memory extraction

**Files:**
- Create: `backend/app/services/memory.py`
- Create: `backend/tests/services/test_memory.py`

**Interfaces:**
- Consumes: complete open-day ledger history for one store, including final weather and activity text.
- Produces: upserted weather/weekday/activity memories with direction, qualitative description, confidence, and latest occurrence; obsolete patterns are removed during the same store refresh.

- [ ] **Step 1: Write failing threshold, isolation, direction, and copy tests**

```python
# backend/tests/services/test_memory.py
async def test_single_activity_is_not_a_memory(memory_engine, store_with_one_activity) -> None:
    memories = await memory_engine.refresh(store_with_one_activity.id, date(2026, 7, 13))
    assert all(memory.memory_type != "activity" for memory in memories)


async def test_repeated_weather_gets_qualitative_direction(memory_engine, weather_history) -> None:
    memories = await memory_engine.refresh(weather_history.store_id, date(2026, 7, 13))
    rain = next(memory for memory in memories if memory.memory_type == "weather" and memory.pattern == "雨")
    assert rain.impact_direction == "下降"
    assert rain.confidence >= 50
    assert "%" not in rain.description
    assert "百分" not in rain.description


async def test_store_histories_never_mix(memory_engine, two_store_history) -> None:
    first = await memory_engine.refresh(two_store_history.first_id, date(2026, 7, 13))
    second = await memory_engine.refresh(two_store_history.second_id, date(2026, 7, 13))
    assert {(m.memory_type, m.pattern, m.description) for m in first} != {
        (m.memory_type, m.pattern, m.description) for m in second
    }


async def test_visibility_filters_below_fifty(memory_repo, store) -> None:
    await memory_repo.add(store.id, "weekday", "星期一", confidence=49)
    await memory_repo.add(store.id, "weekday", "星期二", confidence=50)
    assert [m.pattern for m in await memory_repo.visible(store.id)] == ["星期二"]
```

- [ ] **Step 2: Run memory tests and verify service is missing**

Run: `cd backend && pytest tests/services/test_memory.py -q`

Expected: FAIL importing `app.services.memory`.

- [ ] **Step 3: Implement grouping, direction, confidence, and descriptions**

```python
# backend/app/services/memory.py
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PatternStats:
    pattern: str
    samples: int
    average: Decimal
    baseline: Decimal


def classify_direction(stats: PatternStats) -> str:
    if stats.baseline == 0:
        return "无明显影响"
    ratio = (stats.average - stats.baseline) / stats.baseline
    if ratio >= Decimal("0.15"):
        return "上升"
    if ratio <= Decimal("-0.15"):
        return "下降"
    return "无明显影响"


def confidence(stats: PatternStats) -> int:
    if stats.samples < 3 or stats.baseline == 0:
        return 0
    relative_gap = abs(stats.average - stats.baseline) / stats.baseline
    sample_score = min(40, stats.samples * 5)
    separation_score = min(30, int(relative_gap * 100))
    return min(95, 25 + sample_score + separation_score)


def description(memory_type: str, pattern: str, direction: str) -> str:
    subject = {"weather": f"{pattern}天气", "weekday": pattern, "activity": f"活动“{pattern}”"}[memory_type]
    ending = {"上升": "经营表现通常更好。", "下降": "经营表现通常偏弱。",
              "无明显影响": "暂未显示出明显差异。"}[direction]
    return f"历史记录中，{subject}时{ending}"
```

`MemoryEngine.refresh` loads only `is_open=营业` rows for one store, computes the store baseline, groups by final `weather`, localized weekday label, and normalized exact activity text (trim whitespace, collapse runs, casefold for identity, preserve first display text). It requires 4 samples for weather/weekday and 3 for activity. It upserts current patterns, removes patterns that no longer meet thresholds, sets `last_seen_at` from the latest matching record, and marks previously unscanned rows `scanned=true` only after memory writes succeed.

- [ ] **Step 4: Run memory tests and verify confidence/output boundaries**

Run: `cd backend && pytest tests/services/test_memory.py -q`

Expected: single events are ignored; thresholds, all three memory types, store isolation, upsert/removal, latest occurrence, scan-after-success, direction, confidence bounds, copy wording, and visibility filtering pass.

- [ ] **Step 5: Commit the memory engine**

```bash
git add backend/app/services/memory.py backend/tests/services/test_memory.py
git commit -m "feat: add conservative store memory engine"
```

### Task 3: Make scheduled execution store-local and idempotent

**Files:**
- Modify: `backend/app/services/scheduler.py`
- Create: `backend/app/services/daily_workflow.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/services/test_scheduler.py`
- Create: `backend/tests/services/test_daily_workflow.py`

**Interfaces:**
- Consumes: active stores with IANA time zones, weather/briefing/memory services, missing-ledger alert service, and task logs.
- Produces: exactly one registered 04:00 cron job per active store/time zone and idempotent step logs keyed by store/local-date/task.

- [ ] **Step 1: Write failing timezone, order, duplicate, and failure tests**

```python
# backend/tests/services/test_scheduler.py
def test_each_store_gets_its_own_timezone(scheduler_service, rome_store, utc_store) -> None:
    scheduler_service.reconcile([rome_store, utc_store])
    assert scheduler_service.scheduler.get_job(f"daily:{rome_store.id}").trigger.timezone.key == "Europe/Rome"
    assert scheduler_service.scheduler.get_job(f"daily:{utc_store.id}").trigger.timezone.key == "UTC"


async def test_same_daily_run_key_executes_once(run_once, operation) -> None:
    first = await run_once("daily:1:2026-07-13:today_weather", "today_weather", 1, operation)
    second = await run_once("daily:1:2026-07-13:today_weather", "today_weather", 1, operation)
    assert operation.calls == 1
    assert first.status == "success"
    assert second.status == "skipped"
```

```python
# backend/tests/services/test_daily_workflow.py
async def test_daily_workflow_runs_required_order(workflow, spy_steps) -> None:
    await workflow.run(store_id=1, local_date=date(2026, 7, 13))
    assert spy_steps.calls == [
        "today_weather", "tomorrow_weather", "yesterday_weather", "scan_data",
        "refresh_memory", "yesterday_briefing", "today_briefing", "tomorrow_briefing",
        "missing_yesterday", "finish_log",
    ]
```

- [ ] **Step 2: Run scheduling tests and verify missing daily workflow**

Run: `cd backend && pytest tests/services/test_scheduler.py tests/services/test_daily_workflow.py -q`

Expected: FAIL because idempotent runner and daily workflow are absent.

- [ ] **Step 3: Implement database-backed run-once semantics**

```python
# backend/app/services/scheduler.py
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.operations import ScheduledTaskLog


def sanitized(exc: Exception) -> str:
    return f"{type(exc).__name__}: scheduled operation failed"


async def run_once(session_factory, run_key: str, task_type: str, store_id: int | None, operation):
    async with session_factory() as session:
        log = ScheduledTaskLog(
            run_key=run_key, store_id=store_id, task_type=task_type, status="skipped",
            message="Task claimed", retry_count=0, started_at=datetime.now(UTC), finished_at=None,
        )
        session.add(log)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return ScheduledTaskLog(run_key=run_key, store_id=store_id, task_type=task_type,
                                    status="skipped", message="Duplicate run skipped", retry_count=0,
                                    started_at=datetime.now(UTC), finished_at=datetime.now(UTC))
    try:
        await operation()
    except Exception as exc:
        async with session_factory() as session:
            stored = await session.scalar(select(ScheduledTaskLog).where(ScheduledTaskLog.run_key == run_key))
            stored.status, stored.message, stored.finished_at = "failed", sanitized(exc), datetime.now(UTC)
            await session.commit()
        return stored
    async with session_factory() as session:
        stored = await session.scalar(select(ScheduledTaskLog).where(ScheduledTaskLog.run_key == run_key))
        stored.status, stored.message, stored.finished_at = "success", "Task completed", datetime.now(UTC)
        await session.commit()
        return stored
```

- [ ] **Step 4: Reconcile cron jobs and implement ordered workflow continuation**

Use `CronTrigger(hour=4, minute=0, timezone=ZoneInfo(store.timezone))`, job id `daily:{store.id}`, and `replace_existing=True`. The FastAPI lifespan starts the scheduler after reconciling active stores and shuts it down cleanly; an administrator store-timezone/active change triggers reconciliation. `DailyWorkflow.run` calls all ten steps through stable keys `daily:{store_id}:{local_date}:{task_type}`. A failed weather step is logged and does not prevent later scan/card/missing-ledger steps; a failed database memory/card step logs failure and continues only when its dependent input is available. The scan step compares every stored `daily_revenue` with included category items and upserts a `data_anomaly` alert for mismatches. The missing-yesterday step upserts `missing_ledger` when absent and resolves the same keyed alert after backfill.

Run: `cd backend && pytest tests/services/test_scheduler.py tests/services/test_daily_workflow.py -q`

Expected: time-zone registration, DST-aware trigger construction, inactive-job removal, duplicate suppression, required order, non-blocking weather failure, dependency-aware continuation, and sanitized task logs pass.

- [ ] **Step 5: Commit idempotent daily scheduling**

```bash
git add backend/app/services/scheduler.py backend/app/services/daily_workflow.py backend/app/main.py backend/tests/services
git commit -m "feat: add idempotent store-local daily workflow"
```

### Task 4: Add persistent weather compensation and deduplicated alerts

**Files:**
- Create: `backend/app/services/alerts.py`
- Create: `backend/app/services/weather_compensation.py`
- Modify: `backend/app/services/scheduler.py`
- Create: `backend/tests/services/test_weather_compensation.py`

**Interfaces:**
- Consumes: Phase 1 WeatherService, records with incomplete automatic weather fields, persistent retry logs, and system alerts.
- Produces: two-hour interval compensation, retry count on `weather:{store_id}:{date}`, success completion, and one unresolved alert after the third failure.

- [ ] **Step 1: Write failing retry/preservation/deduplication tests**

```python
# backend/tests/services/test_weather_compensation.py
async def test_retry_fills_auto_fields_without_overwriting_manual_weather(compensation, manual_record, weather_ok) -> None:
    manual_record.weather = "用户选择：阴"
    manual_record.weather_edited = True
    await compensation.run(limit=50)
    await manual_record.refresh()
    assert manual_record.weather == "用户选择：阴"
    assert manual_record.weather_auto == "晴"
    assert manual_record.weather_code == 0


async def test_third_failure_creates_one_alert(compensation, missing_record, weather_failure, alert_repo) -> None:
    await compensation.run()
    await compensation.run()
    await compensation.run()
    await compensation.run()
    alerts = await alert_repo.unresolved(store_id=missing_record.store_id, alert_type="weather_failed")
    assert len(alerts) == 1
    assert "2026-07-12" in alerts[0].message
```

- [ ] **Step 2: Run compensation tests and verify missing services**

Run: `cd backend && pytest tests/services/test_weather_compensation.py -q`

Expected: FAIL importing compensation and alert services.

- [ ] **Step 3: Implement reusable alert upsert and retry-row updates**

```python
# backend/app/services/alerts.py
from sqlalchemy import select

from app.models.operations import SystemAlert


class AlertService:
    def __init__(self, session):
        self.session = session

    async def upsert(self, *, store_id: int | None, alert_type: str, level: str,
                     message_key: str, message: str) -> SystemAlert:
        alert = await self.session.scalar(select(SystemAlert).where(
            SystemAlert.store_id == store_id,
            SystemAlert.alert_type == alert_type,
            SystemAlert.is_resolved.is_(False),
            SystemAlert.message.like(f"[{message_key}]%"),
        ))
        if alert is None:
            alert = SystemAlert(store_id=store_id, alert_type=alert_type, level=level,
                                message=f"[{message_key}] {message}", is_resolved=False)
            self.session.add(alert)
        else:
            alert.level = level
            alert.message = f"[{message_key}] {message}"
        return alert
```

`WeatherCompensation` selects at most 50 oldest records missing any automatic weather field. It locks/creates one `ScheduledTaskLog` with `run_key=weather:{store_id}:{date}` and `task_type=weather_backfill`. Failure increments the existing row's `retry_count`, sets status `failed`, and after count 3 calls alert upsert with `message_key={store_id}:{date}`. Success snapshots the record, fills automatic fields, sets final `weather` only when `weather_edited=false` and final weather is empty, writes an `operation_domain=ledger`, `operation_source=system` audit, sets the task log `success`, and resolves the matching weather alert if present. Also modify `run_once` so any non-weather scheduled exception upserts one keyed `scheduled_task_failed` alert; a later successful run with the same store/task family resolves it.

- [ ] **Step 4: Schedule the interval job and verify all retries**

Register one `IntervalTrigger(hours=2)` job id `weather-compensation`, `max_instances=1`, `coalesce=True`. The job catches errors per record, so one store/date cannot stop the remaining batch.

Run: `cd backend && pytest tests/services/test_weather_compensation.py tests/services/test_scheduler.py -q`

Expected: retry persistence across service instances, count increments, third-failure alert, alert deduplication, manual-final-weather preservation, success resolution, per-record isolation, limit ordering, and singleton interval-job tests pass.

- [ ] **Step 5: Commit weather compensation and alerts**

```bash
git add backend/app/services/alerts.py backend/app/services/weather_compensation.py backend/app/services/scheduler.py backend/tests/services
git commit -m "feat: add persistent weather compensation alerts"
```

### Task 5: Enrich cached briefings with visible memories and safe model fallback

**Files:**
- Modify: `backend/app/services/briefing.py`
- Modify: `backend/app/api/routes/dashboard.py`
- Create: `backend/tests/services/test_memory_briefing.py`
- Create: `backend/tests/api/test_dashboard_memory.py`

**Interfaces:**
- Consumes: yesterday/today/tomorrow ledger/weather facts, confidence-filtered memories, and optional Phase 3 LLM gateway.
- Produces: short cached card copy with at most one relevant memory hint, deterministic fallback on model failure, and targeted yesterday regeneration after backfill/edit.

- [ ] **Step 1: Write failing confidence, relevance, fallback, and targeted-refresh tests**

```python
# backend/tests/services/test_memory_briefing.py
async def test_today_card_uses_only_relevant_visible_memory(briefing_service, today_weather, memory_repo) -> None:
    await memory_repo.add(today_weather.store_id, "weather", "雨", confidence=72,
                          description="历史记录中，雨天气时经营表现通常偏弱。")
    await memory_repo.add(today_weather.store_id, "weekday", "星期一", confidence=49,
                          description="hidden")
    card = await briefing_service.generate(today_weather.store_id, "today", today_weather.date)
    assert "雨天气时经营表现通常偏弱" in card.content
    assert "hidden" not in card.content


async def test_llm_failure_keeps_deterministic_card(briefing_service, failing_llm, today_weather) -> None:
    card = await briefing_service.generate(today_weather.store_id, "today", today_weather.date)
    assert card.content.startswith("今天")
    assert card.content != ""


async def test_yesterday_edit_regenerates_only_yesterday_card(dashboard_spy, ledger_edit) -> None:
    await ledger_edit.save()
    assert dashboard_spy.regenerated == ["yesterday"]
```

- [ ] **Step 2: Run briefing tests and verify memory is not yet integrated**

Run: `cd backend && pytest tests/services/test_memory_briefing.py tests/api/test_dashboard_memory.py -q`

Expected: FAIL because cards do not query visible memories or target regeneration.

- [ ] **Step 3: Select at most one relevant memory and build deterministic copy**

```python
# backend/app/services/briefing.py (memory selection helper)
async def select_memory(session, *, store_id: int, weather: str | None,
                        weekday: str, activity: str | None):
    candidates = (await session.scalars(select(AgentMemory).where(
        AgentMemory.store_id == store_id,
        AgentMemory.confidence >= 50,
    ).order_by(AgentMemory.confidence.desc(), AgentMemory.last_seen_at.desc()))).all()
    for memory in candidates:
        if memory.memory_type == "weather" and memory.pattern == weather:
            return memory
        if memory.memory_type == "weekday" and memory.pattern == weekday:
            return memory
        if memory.memory_type == "activity" and activity and memory.pattern.casefold() == activity.strip().casefold():
            return memory
    return None
```

The deterministic card concatenates facts first and one hint second, capped at 180 Chinese characters. If Phase 3 is configured, model polishing receives only these facts/hint plus the instruction `保持简短、温和、定性，不添加百分比或绝对预测`; output is rejected when it contains `%`, `百分`, or exceeds 180 characters, and the deterministic copy is stored instead.

- [ ] **Step 4: Wire targeted refresh and verify cache-only reads**

After a successful ledger create/update/delete/rollback for the store's local yesterday, enqueue/regenerate only `yesterday`; other dates do not regenerate cards synchronously. `GET /dashboard/{store_id}` reads three rows and performs no external calls. Manual refresh regenerates requested cards behind the existing five-minute rate limit.

Run: `cd backend && pytest tests/services/test_memory_briefing.py tests/api/test_dashboard_memory.py tests/api/test_dashboard.py tests/api/test_ledger.py -q`

Expected: confidence filtering, relevance priority, one-hint limit, cautious copy, model rejection/fallback, targeted yesterday regeneration, rate limiting, store isolation, and cache-only read tests pass.

- [ ] **Step 5: Commit memory-aware briefings**

```bash
git add backend/app/services/briefing.py backend/app/api/routes/dashboard.py backend/tests
git commit -m "feat: add memory-aware cached briefings"
```

### Task 6: Complete administrator observability UI and the Phase 4 release gate

**Files:**
- Modify: `backend/app/api/routes/admin.py`
- Create: `backend/tests/api/test_admin_operations.py`
- Create: `frontend/src/components/admin/AlertList.tsx`
- Create: `frontend/src/components/admin/TaskLogList.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx`
- Modify: `frontend/src/components/BriefingCards.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`
- Modify: `frontend/src/pages/AdminPage.test.tsx`
- Create: `frontend/tests/automation-observability.spec.ts`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: task-log, alert-resolution, and cached-dashboard APIs.
- Produces: filterable administrator task/alert views, resolution workflow, user-facing memory hint rendering, documented recovery operations, and automated release verification.

- [ ] **Step 1: Write failing API/UI observability tests**

```python
# backend/tests/api/test_admin_operations.py
async def test_admin_can_resolve_alert_and_user_cannot(admin_client, auth_client, unresolved_alert) -> None:
    assert (await auth_client.patch(f"/api/admin/alerts/{unresolved_alert.id}/resolve")).status_code == 403
    response = await admin_client.patch(f"/api/admin/alerts/{unresolved_alert.id}/resolve")
    assert response.status_code == 200
    assert response.json()["is_resolved"] is True
    assert response.json()["resolved_at"] is not None


async def test_task_log_filters_are_stable(admin_client, scheduled_logs) -> None:
    response = await admin_client.get("/api/admin/task-logs?status=failed&task_type=weather_backfill")
    assert response.status_code == 200
    assert all(item["status"] == "failed" and item["task_type"] == "weather_backfill"
               for item in response.json()["items"])
```

```tsx
// frontend/src/pages/AdminPage.test.tsx
it("filters failed tasks and resolves a warning", async () => {
  renderAdminPage(automationFixture());
  await user.selectOptions(await screen.findByLabelText("任务状态"), "failed");
  expect(await screen.findByText("天气补偿失败")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "标记已处理" }));
  expect(await screen.findByText("已处理")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run observability tests and verify resolution/filter contracts are missing**

Run: `cd backend && pytest tests/api/test_admin_operations.py -q; cd ../frontend && npm test -- AdminPage`

Expected: backend and frontend tests fail until resolution and filter behaviors are implemented.

- [ ] **Step 3: Implement administrator operations and pagination**

`GET /admin/task-logs` supports store, task type, status, start/end time, page, and page size; it orders newest first. `GET /admin/alerts` supports store, level, type, resolved state, and pagination. `PATCH /admin/alerts/{id}/resolve` sets `is_resolved=true` and `resolved_at=now`; a second call is idempotent. All endpoints require `admin`, sanitize stored errors, and return total/items/page/page_size.

- [ ] **Step 4: Build UI, document recovery, and run the complete release gate**

`AlertList` shows level, store, message, timestamp, state, and resolve action. `TaskLogList` shows type, status, retry count, sanitized message, start/finish times, and filters. `BriefingCards` visually separates the optional memory hint without displaying confidence as a prediction. README documents scheduler single-process requirement, 04:00 store-local timing, manual job invocation, retry threshold, alert resolution, memory thresholds, and how to inspect task logs.

Run: `cd backend && ruff check . && pytest --cov=app; cd ../frontend && npm test && npm run build && npx playwright test tests/automation-observability.spec.ts; cd .. && docker compose config && docker compose build`

Expected: all regressions pass; browser test verifies admin-only access, failed-task filtering, alert resolution, cached home cards, visible high-confidence hint, absent low-confidence hint, and no waiting spinner tied to external services; images build.

- [ ] **Step 5: Commit the Phase 4 release**

```bash
git add backend frontend .github/workflows/ci.yml README.md
git commit -m "feat: complete automation memory and observability"
```

## Phase 4 acceptance checklist

- Every active store has one 04:00 job in its own time zone; disabled stores have none.
- Stable task keys prevent duplicate daily work after restart or repeated dispatch.
- Daily steps follow the spec order and weather failure cannot stop scan/briefing/missing-ledger work.
- Weather retry count persists, the third failure creates one alert, success fills auto fields and preserves manual final weather.
- Memories are store-isolated, limited to three types, ignore one-off events, and hide confidence below 50.
- Cards store at most one relevant qualitative hint and always fall back to deterministic copy.
- Home reads remain cache-only; administrators can filter logs, inspect retries, and resolve alerts.
- The complete four-phase application still deploys as only API and web containers against host MySQL.
