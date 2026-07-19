# AutoLava AI Usability Foundation Implementation Plan

> Historical implementation record retained for provenance. Database inspection and logical
> backup/restore steps are superseded and are not current runtime instructions.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved usability redesign, versioned dual-mode revenue model, bounded rollback history, safer administration, map-style store addresses, and extension seams for later workforce, AI, and automation phases.

**Architecture:** Extend the existing FastAPI/SQLAlchemy domain model with immutable income-configuration versions and record-level snapshots, while keeping existing total-revenue records readable. Split the React application shell and admin area into focused modules; use stable capability, event, geocoding, and analytics interfaces so later phases add modules instead of rewriting ledger code.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, Alembic, MySQL, pytest, React, TypeScript, TanStack Query, Tailwind CSS, Recharts, Leaflet 1.9.4, Vitest, Playwright.

## Global Constraints

- Work only in the existing isolated worktree `D:/work/myself/AI-try/AutoLava-AI/.worktrees/phase-1-foundation` on `feature/phase-1-foundation`.
- The current runtime data may be in `autolava_test`; create a verified backup and move runtime data away from the test database before any backend test that clears tables.
- The system records revenue only. Do not introduce profit, expense, or arbitrary formula semantics.
- The home page remains exactly three cards—yesterday, today, tomorrow—followed by “立即记账”.
- A store without enabled composition accepts a directly entered total. A store with enabled composition rejects a client-entered total and calculates it from items marked `include_in_total`.
- Existing records remain historical total records; do not invent component splits.
- Sulmona activity data must be cleared while dates and revenue amounts remain unchanged.
- Configuration rollback retains at most 20 versions and at most 180 days. Ledger rollback retains at most 10 versions per record and at most 365 days.
- Do not add an Excel-import UI.
- Never hard-code or commit the administrator password, database password, JWT secret, Geoapify key, or browser session tokens.
- Geoapify autocomplete is optional and server-side; without a key, retain explicit Open-Meteo place search plus manual map pin/current-location fallback.
- OpenStreetMap tiles must show attribution, must not be prefetched, and the tile URL must remain configurable.
- Implement with TDD: failing test, observed failure, minimal implementation, passing targeted tests, then commit.
- Do not run the full backend suite against a database containing user data.

---

### Task 1: Protect Runtime Data and Establish a Safe Baseline

**Files:**
- Create: `scripts/backup-local-db.ps1`
- Create: `scripts/restore-local-db.ps1`
- Create: `backend/app/scripts/inspect_runtime_database.py`
- Create: `backend/tests/test_runtime_database_guard.py`
- Modify: `scripts/start-local.ps1`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: `AUTOLAVA_DATABASE_URL` and the existing launcher environment-loading behavior.
- Produces: `inspect_database(url: str) -> DatabaseIdentity`, a timestamped SQL backup command, and a launcher guard that refuses to start normal runtime on `autolava_test`.

- [ ] **Step 1: Write the failing runtime-database guard tests**

```python
from app.scripts.inspect_runtime_database import inspect_database_url


def test_runtime_guard_rejects_test_database() -> None:
    identity = inspect_database_url("mysql+asyncmy://user:secret@127.0.0.1/autolava_test")
    assert identity.database == "autolava_test"
    assert identity.is_test_database is True


def test_runtime_guard_accepts_local_database_without_exposing_password() -> None:
    identity = inspect_database_url("mysql+asyncmy://user:secret@127.0.0.1/autolava_local")
    assert identity.database == "autolava_local"
    assert "secret" not in repr(identity)
```

- [ ] **Step 2: Run the focused test and verify the missing-module failure**

Run: `cd backend; python -m pytest tests/test_runtime_database_guard.py -q`

Expected: FAIL during collection because `app.scripts.inspect_runtime_database` does not exist.

- [ ] **Step 3: Implement the safe URL inspector**

```python
from dataclasses import dataclass
from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class DatabaseIdentity:
    host: str
    database: str
    is_test_database: bool


def inspect_database_url(value: str) -> DatabaseIdentity:
    url = make_url(value)
    database = url.database or ""
    return DatabaseIdentity(
        host=url.host or "",
        database=database,
        is_test_database=database.lower().endswith("_test"),
    )
```

- [ ] **Step 4: Add a password-safe PowerShell backup workflow and launcher guard**

`backup-local-db.ps1` must resolve the database URL from the same env files as the launcher, create `.autolava-local/backups/<database>-<yyyyMMdd-HHmmss>.sql`, pass credentials to `mysqldump` through a temporary `--defaults-extra-file`, remove the temporary file in `finally`, and verify that the output exists and is non-empty. If `mysqldump` is unavailable, stop with an actionable message; never fall back to a logical copy without telling the user.

`restore-local-db.ps1 -BackupPath <absolute-sql-path> -TargetDatabase autolava_local` must validate that the backup is inside `.autolava-local/backups`, reject target names ending in `_test`, create the target database with `utf8mb4`, stream the SQL through `mysql --defaults-extra-file=<temporary-file>`, remove the temporary file in `finally`, and verify the restored table/record counts. It must never overwrite an existing non-empty target unless `-Force` is explicitly supplied.

In `start-local.ps1`, parse only the database name and reject `*_test` unless the caller passes a new explicit `-AllowTestDatabase` switch. Do not print the URL.

- [ ] **Step 5: Back up current runtime data before running any destructive test**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/backup-local-db.ps1`

Expected: a non-empty SQL file under `.autolava-local/backups/` and output containing only the database name and backup path, never credentials.

- [ ] **Step 6: Create `autolava_local`, restore the backup, and point local runtime at it**

Run `scripts/restore-local-db.ps1` against the verified backup to create `autolava_local`, update only the ignored local `.env`/`.autolava-db.env`, then run the inspector against the effective URL.

Expected: runtime database `autolava_local`; test configuration remains `autolava_test`; record count, Sulmona date range, and revenue sum match the source database.

- [ ] **Step 7: Run targeted tests and commit**

Run: `cd backend; python -m pytest tests/test_runtime_database_guard.py tests/test_local_launcher.py -q`

Expected: PASS.

```bash
git add scripts/backup-local-db.ps1 scripts/restore-local-db.ps1 scripts/start-local.ps1 backend/app/scripts/inspect_runtime_database.py backend/tests/test_runtime_database_guard.py backend/tests/test_local_launcher.py .env.example README.md
git commit -m "safety: separate local runtime and test databases"
```

---

### Task 2: Add the Versioned Income-Configuration Schema

**Files:**
- Create: `backend/alembic/versions/0004_usability_foundation.py`
- Create: `backend/app/models/income_config.py`
- Modify: `backend/app/models/ledger.py`
- Modify: `backend/app/models/audit.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/test_schema.py`
- Create: `backend/tests/services/test_income_config.py`

**Interfaces:**
- Produces: `IncomeConfigVersion`, `IncomeConfigVersionItem`, `IncomeMode`, record `row_version`, item snapshots, archive timestamps, and audit snapshot expiry metadata.
- Consumed by: Tasks 3, 4, 5, 8, 9, 10, and 11.

- [ ] **Step 1: Write schema tests for immutable versions and snapshots**

```python
async def test_income_config_schema_supports_immutable_snapshots(db_session, store_factory, user_factory):
    store = await store_factory(name="Versioned")
    actor = await user_factory(username="owner", password="secret", role="admin")
    version = IncomeConfigVersion(store_id=store.id, version=1, enabled=True, created_by=actor.id)
    db_session.add(version)
    await db_session.flush()
    assert version.id is not None
    assert version.version == 1


def test_schema_declares_record_mode_and_optimistic_version():
    columns = StoreDailyRecord.__table__.c
    assert {"income_mode", "income_config_version_id", "row_version"} <= set(columns.keys())
    item_columns = DailyIncomeItem.__table__.c
    assert {"category_name", "include_in_total", "sort_order"} <= set(item_columns.keys())
```

- [ ] **Step 2: Run the schema tests and verify failure**

Run: `cd backend; python -m pytest tests/test_schema.py tests/services/test_income_config.py -q`

Expected: FAIL because the new models and columns are absent.

- [ ] **Step 3: Define focused SQLAlchemy models**

```python
class IncomeConfigVersion(Base):
    __tablename__ = "income_config_versions"
    __table_args__ = (UniqueConstraint("store_id", "version", name="uq_income_config_store_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    version: Mapped[int]
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    items: Mapped[list["IncomeConfigVersionItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class IncomeConfigVersionItem(Base):
    __tablename__ = "income_config_version_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    config_version_id: Mapped[int] = mapped_column(ForeignKey("income_config_versions.id", ondelete="CASCADE"))
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("income_categories.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(100))
    include_in_total: Mapped[bool]
    is_active: Mapped[bool]
    sort_order: Mapped[int]
```

Extend existing models with:

```python
IncomeMode = Literal["legacy_total", "composed"]

# IncomeCategory
archived_at: Mapped[datetime | None]

# StoreDailyRecord
income_mode: Mapped[str] = mapped_column(String(20), default="legacy_total")
income_config_version_id: Mapped[int | None] = mapped_column(
    ForeignKey("income_config_versions.id", ondelete="SET NULL")
)
row_version: Mapped[int] = mapped_column(default=1)

# DailyIncomeItem
category_name: Mapped[str] = mapped_column(String(100))
include_in_total: Mapped[bool]
sort_order: Mapped[int]

# AuditLog
snapshot_expires_at: Mapped[datetime | None]
```

- [ ] **Step 4: Write migration `0004` with safe backfill**

The upgrade must:

1. Create the two version tables.
2. Add nullable snapshot columns first.
3. Backfill every existing record with `income_mode='legacy_total'`, `row_version=1`.
4. Backfill every existing item from its current category name/include/sort values.
5. Make item snapshot columns non-null.
6. Add indexes on `(store_id, version)`, `(record_id, sort_order)`, and `(operation_domain, record_id, created_at)`.
7. Keep `daily_revenue` unchanged.

The downgrade removes only new structures and columns; it must not recalculate revenue.

- [ ] **Step 5: Upgrade the test schema and run focused tests**

Run: `cd backend; alembic upgrade head`

Expected: revision `0004_usability_foundation` applied to `autolava_test` only.

Run: `cd backend; python -m pytest tests/test_schema.py tests/services/test_income_config.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/0004_usability_foundation.py backend/app/models backend/tests/test_schema.py backend/tests/services/test_income_config.py
git commit -m "feat: add versioned income configuration schema"
```

---

### Task 3: Implement Income Configuration Publishing, Archiving, Restore, and Deletion

**Files:**
- Create: `backend/app/schemas/income_config.py`
- Create: `backend/app/services/income_config.py`
- Create: `backend/app/api/routes/income_config.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/api/routes/admin.py`
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/tests/api/test_admin.py`
- Create: `backend/tests/api/test_income_config.py`

**Interfaces:**
- Produces: `IncomeConfigService.current(store_id)`, `publish(store_id, body, actor)`, `restore(store_id, version_id, actor)`, `archive(category_id, actor)`, and `delete_unused(category_id, actor)`.
- HTTP: `GET/PUT /api/admin/stores/{store_id}/income-config`, `GET /versions`, `POST /versions/{version_id}/restore`, `POST /income-categories/{id}/archive`, `POST /income-categories/{id}/restore`, existing DELETE for unused categories.

- [ ] **Step 1: Write failing API tests for the approved lifecycle**

```python
async def test_publish_selects_exact_items_for_total(admin_client, store_factory):
    store = await store_factory(name="Configured")
    response = await admin_client.put(
        f"/api/admin/stores/{store.id}/income-config",
        json={
            "enabled": True,
            "items": [
                {"category_id": None, "name": "现金", "include_in_total": True, "is_active": True, "sort_order": 1},
                {"category_id": None, "name": "外卖平台", "include_in_total": False, "is_active": True, "sort_order": 2},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["formula"] == "总收入 = 现金"


async def test_used_category_can_be_archived_and_restored_but_not_deleted(admin_client, category_with_item):
    archived = await admin_client.post(f"/api/admin/income-categories/{category_with_item.id}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert (await admin_client.delete(f"/api/admin/income-categories/{category_with_item.id}")).status_code == 409
    assert (await admin_client.post(f"/api/admin/income-categories/{category_with_item.id}/restore")).status_code == 200
```

- [ ] **Step 2: Run tests and verify 404/failure**

Run: `cd backend; python -m pytest tests/api/test_income_config.py tests/api/test_admin.py -q`

Expected: FAIL because configuration routes and archive state are absent.

- [ ] **Step 3: Define exact request and response schemas**

```python
class IncomeConfigItemBody(BaseModel):
    category_id: int | None = None
    name: CategoryName
    include_in_total: bool
    is_active: bool = True
    sort_order: int = 0


class IncomeConfigPublishBody(BaseModel):
    enabled: bool
    items: list[IncomeConfigItemBody]


class IncomeConfigResponse(BaseModel):
    store_id: int
    version_id: int | None
    version: int
    enabled: bool
    formula: str
    items: list[IncomeConfigItemResponse]
```

- [ ] **Step 4: Implement atomic publishing**

`publish` must lock versions for the store, validate unique IDs and names, reject categories from another store, create new categories for `category_id=None`, ignore archived categories, create a new immutable version with copied item snapshots, and add an admin audit entry. It must never update an older `IncomeConfigVersionItem`.

The legacy `POST/PATCH /api/admin/income-categories` routes must delegate to `IncomeConfigService` and publish a new immutable version; no API path may mutate a category in place without versioning.

Formula construction is deterministic:

```python
included = [item.name for item in sorted(items, key=lambda item: (item.sort_order, item.id)) if item.is_active and item.include_in_total]
formula = "总收入 = " + " + ".join(included) if included else "总收入 = €0.00"
```

- [ ] **Step 5: Implement archive, restore, delete, and version restore**

Archive sets `archived_at=func.now()` and publishes a new version without that item. Restore clears `archived_at` but does not silently enable the item; the next publish selects its state. Permanent delete checks `daily_income_items`; only categories never referenced by a ledger record may be deleted. Historical configuration items keep their name/include/order snapshot and receive `category_id=NULL` through `ON DELETE SET NULL`. Restoring an old configuration creates a new latest version rather than mutating history; if an old item has `category_id=NULL`, restore recreates a stable category from its snapshot before publishing.

- [ ] **Step 6: Run focused tests and commit**

Run: `cd backend; python -m pytest tests/api/test_income_config.py tests/api/test_admin.py -q`

Expected: PASS.

```bash
git add backend/app/schemas/income_config.py backend/app/services/income_config.py backend/app/api/routes/income_config.py backend/app/api/router.py backend/app/api/routes/admin.py backend/app/schemas/admin.py backend/tests/api/test_income_config.py backend/tests/api/test_admin.py
git commit -m "feat: manage versioned income compositions"
```

---

### Task 4: Implement Dual-Mode Ledger Writes, Immutable Snapshots, and Concurrency

**Files:**
- Create: `backend/app/events/ledger.py`
- Modify: `backend/app/schemas/ledger.py`
- Modify: `backend/app/services/ledger.py`
- Modify: `backend/app/services/audit.py`
- Modify: `backend/app/services/rollback.py`
- Modify: `backend/app/api/routes/ledger.py`
- Modify: `backend/tests/services/test_ledger.py`
- Modify: `backend/tests/api/test_ledger.py`
- Modify: `backend/tests/services/test_rollback.py`

**Interfaces:**
- Consumes: `IncomeConfigService.current()` and immutable version items.
- Produces: `LedgerBody.daily_revenue`, `LedgerBody.config_version_id`, `LedgerBody.expected_version`, `LedgerChanged`, `GET /api/ledger/{store_id}/{date}/form-config`, and record snapshots containing mode/version/item names.

- [ ] **Step 1: Write failing service tests for both modes**

```python
async def test_total_mode_requires_direct_total_and_no_items(ledger_service, store, actor):
    record, created = await ledger_service.upsert(
        store=store,
        record_date=date(2026, 7, 15),
        payload={"is_open": "营业", "daily_revenue": "125.50", "config_version_id": None, "items": []},
        actor=actor,
    )
    assert created is True
    assert record.income_mode == "legacy_total"
    assert record.daily_revenue == Decimal("125.50")


async def test_composed_mode_ignores_client_total_and_uses_snapshot_flags(ledger_service, configured_store, actor):
    with pytest.raises(HTTPException) as error:
        await ledger_service.upsert(
            store=configured_store.store,
            record_date=date(2026, 7, 15),
            payload={"is_open": "营业", "daily_revenue": "999.00", "config_version_id": configured_store.version.id, "items": configured_store.amounts},
            actor=actor,
        )
    assert error.value.status_code == 422
```

- [ ] **Step 2: Write failing concurrency tests**

```python
async def test_stale_expected_version_cannot_overwrite(client_with_record):
    response = await client_with_record.put(
        "/api/ledger/1/2026-07-15?overwrite=true",
        json={"expected_version": 1, "is_open": "营业", "daily_revenue": "10.00", "items": []},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Record changed; reload before saving"
```

- [ ] **Step 3: Run focused tests and verify failure**

Run: `cd backend; python -m pytest tests/services/test_ledger.py tests/api/test_ledger.py tests/services/test_rollback.py -q`

Expected: FAIL on missing fields and concurrency behavior.

- [ ] **Step 4: Extend request validation and snapshots**

```python
class LedgerBody(BaseModel):
    is_open: Literal["营业", "休息", "天气停业"]
    daily_revenue: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    config_version_id: int | None = None
    expected_version: int | None = Field(default=None, ge=1)
    wash_count: int | None = Field(default=None, ge=0)
    weather: str | None = Field(default=None, max_length=50)
    weather_edited: bool = False
    activity: str | None = Field(default=None, max_length=2000)
    items: list[IncomeItemBody] = []
```

`record_snapshot` must include `income_mode`, `income_config_version_id`, `row_version`, and per-item `category_name`, `include_in_total`, and `sort_order`.

The form-config endpoint uses store access, then returns the existing record's immutable snapshot when that date already has a record; otherwise it returns the store's current configuration. Its response is:

```json
{
  "store_id": 1,
  "enabled": true,
  "version_id": 4,
  "version": 4,
  "items": [
    {"category_id": 2, "name": "现金", "include_in_total": true, "is_active": true, "sort_order": 1}
  ]
}
```

- [ ] **Step 5: Implement the two server-authoritative paths**

For a new record, use the latest store configuration. For an existing record, use its stored mode and item snapshot unless an explicit future migration endpoint is added. Total mode requires `daily_revenue` and rejects items. Composed mode rejects `daily_revenue`, requires the bound version, validates every enabled version item exactly once, and calculates with `Decimal` from version snapshot flags.

On update, require `expected_version == record.row_version`, then increment `row_version`. Delete also accepts `expected_version` and rejects stale state. Keep `overwrite=true` as explicit intent separate from concurrency validation.

- [ ] **Step 6: Add the current consumer-backed event seam**

```python
@dataclass(frozen=True)
class LedgerChanged:
    store_id: int
    record_id: int
    record_date: date
    operation: Literal["created", "updated", "deleted", "rolled_back"]
    actor_id: int
    row_version: int | None
```

Return `LedgerChanged` from service writes and let the route use it to refresh the affected briefing. This is a real current consumer and the stable seam for later AI/automation subscribers.

- [ ] **Step 7: Update rollback validation for snapshots and row versions**

Rollback restores snapshot fields, increments the live `row_version` rather than reusing an old concurrency token, validates category snapshots without requiring the current category to remain active, and emits `LedgerChanged(operation="rolled_back")`.

- [ ] **Step 8: Run focused tests and commit**

Run: `cd backend; python -m pytest tests/services/test_ledger.py tests/api/test_ledger.py tests/services/test_rollback.py -q`

Expected: PASS.

```bash
git add backend/app/events backend/app/schemas/ledger.py backend/app/services/ledger.py backend/app/services/audit.py backend/app/services/rollback.py backend/app/api/routes/ledger.py backend/tests/services/test_ledger.py backend/tests/api/test_ledger.py backend/tests/services/test_rollback.py
git commit -m "feat: support total and composed revenue records"
```

---

### Task 5: Add Bounded Rollback Retention and Paginated History

**Files:**
- Create: `backend/app/services/retention.py`
- Modify: `backend/app/services/scheduler.py`
- Modify: `backend/app/api/routes/database.py`
- Modify: `backend/app/schemas/database.py`
- Create: `backend/tests/services/test_retention.py`
- Modify: `backend/tests/api/test_database.py`
- Modify: `backend/tests/services/test_scheduler.py`

**Interfaces:**
- Produces: `RetentionService.prune(now) -> RetentionResult`, paginated `AuditPage`, and scheduler cleanup callback.
- Rules: config maximum 20/180 days; ledger maximum 10 per record/365 days; audit metadata remains after snapshots are cleared.

- [ ] **Step 1: Write failing retention tests**

```python
async def test_prune_keeps_ten_recent_ledger_snapshots_and_metadata(db_session, seeded_audits):
    result = await RetentionService(db_session).prune(now=datetime(2026, 7, 15, tzinfo=UTC))
    rows = list(await db_session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc())))
    assert sum(row.rollbackable for row in rows if row.operation_domain == "ledger") == 10
    assert all(row.description for row in rows)
    assert result.ledger_snapshots_pruned == 2


async def test_config_versions_are_capped_at_twenty_and_180_days(db_session, seeded_versions):
    await RetentionService(db_session).prune(now=datetime(2026, 7, 15, tzinfo=UTC))
    versions = list(await db_session.scalars(select(IncomeConfigVersion).order_by(IncomeConfigVersion.version.desc())))
    assert len(versions) <= 20
    assert versions[0].version == seeded_versions[-1].version
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend; python -m pytest tests/services/test_retention.py tests/api/test_database.py tests/services/test_scheduler.py -q`

Expected: FAIL because retention and paginated history are absent.

- [ ] **Step 3: Implement idempotent pruning**

For old/excess audit entries, set `before_json=None`, `after_json=None`, `rollbackable=False`, and `snapshot_expires_at` to the pruning time; do not delete audit metadata. Delete old income configuration version rows only when they are not current; record snapshots make this safe and the record FK uses `ON DELETE SET NULL`.

Return:

```python
@dataclass(frozen=True)
class RetentionResult:
    ledger_snapshots_pruned: int
    config_versions_pruned: int
```

- [ ] **Step 4: Paginate history instead of returning up to 500 rows**

`GET /api/database/{store_id}/history?page=1&page_size=20&record_id=<optional>` returns:

```json
{"items": [], "total": 0, "page": 1, "page_size": 20}
```

Apply store access checks, stable descending order, and expose `rollbackable=false` after snapshot pruning.

- [ ] **Step 5: Schedule cleanup once daily and log the result**

Add a cleanup callback to the existing background scheduler. A failure records a `ScheduledTaskLog` and does not stop weather/briefing refresh.

- [ ] **Step 6: Run focused tests and commit**

Run: `cd backend; python -m pytest tests/services/test_retention.py tests/api/test_database.py tests/services/test_scheduler.py -q`

Expected: PASS.

```bash
git add backend/app/services/retention.py backend/app/services/scheduler.py backend/app/api/routes/database.py backend/app/schemas/database.py backend/tests/services/test_retention.py backend/tests/api/test_database.py backend/tests/services/test_scheduler.py
git commit -m "feat: bound rollback history and paginate audits"
```

---

### Task 6: Add Capability Checks and Administrator Safety Guards

**Files:**
- Modify: `backend/app/services/access.py`
- Modify: `backend/app/api/deps.py`
- Modify: `backend/app/api/routes/admin.py`
- Modify: `backend/app/api/routes/database.py`
- Modify: `backend/app/api/routes/ledger.py`
- Modify: `backend/tests/api/test_admin.py`
- Create: `backend/tests/services/test_access.py`

**Interfaces:**
- Produces: `Capability` literal, `has_capability(user, capability)`, `require_capability(capability)`, self-deactivation guard, and last-active-admin guard.

- [ ] **Step 1: Write failing safety tests**

```python
async def test_admin_cannot_deactivate_self(admin_client, administrator):
    response = await admin_client.patch(f"/api/admin/users/{administrator.id}", json={"is_active": False})
    assert response.status_code == 409
    assert response.json()["detail"] == "You cannot deactivate your current account"


async def test_concurrent_admin_deactivation_keeps_one_active_admin(
    first_admin_client, second_admin_client, first_admin, second_admin, db_session
):
    responses = await asyncio.gather(
        first_admin_client.patch(f"/api/admin/users/{second_admin.id}", json={"is_active": False}),
        second_admin_client.patch(f"/api/admin/users/{first_admin.id}", json={"is_active": False}),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    active_admins = await db_session.scalar(
        select(func.count()).select_from(User).where(
            User.role == "admin", User.is_active.is_(True)
        )
    )
    assert active_admins == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend; python -m pytest tests/services/test_access.py tests/api/test_admin.py -q`

Expected: FAIL because guards and capability mapping are absent.

- [ ] **Step 3: Implement named capabilities without changing current roles**

```python
Capability = Literal[
    "ledger.view", "ledger.create", "ledger.edit", "ledger.delete",
    "analytics.view", "income_config.manage", "users.manage", "stores.manage", "audit.view",
]

ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    "user": frozenset({"ledger.view", "ledger.create", "ledger.edit", "analytics.view"}),
    "admin": frozenset(get_args(Capability)),
}
```

Keep store membership checks separate from capability checks. Later roles extend this map without changing ledger business rules.

- [ ] **Step 4: Lock active admins during deactivation**

Within one transaction, lock the target user and active admin rows. Reject self-deactivation. Reject a change that would leave fewer than one active admin. Add an audit only after the checks pass.

- [ ] **Step 5: Run focused tests and commit**

Run: `cd backend; python -m pytest tests/services/test_access.py tests/api/test_admin.py tests/api/test_ledger.py tests/api/test_database.py -q`

Expected: PASS.

```bash
git add backend/app/services/access.py backend/app/api/deps.py backend/app/api/routes/admin.py backend/app/api/routes/database.py backend/app/api/routes/ledger.py backend/tests/services/test_access.py backend/tests/api/test_admin.py
git commit -m "feat: add extensible capabilities and admin guards"
```

---

### Task 7: Clean Sulmona Data with a Verified, Re-runnable Command

**Files:**
- Create: `backend/app/scripts/cleanup_sulmona.py`
- Create: `backend/app/scripts/cleanup_fixture_stores.py`
- Create: `backend/tests/test_cleanup_sulmona.py`
- Create: `backend/tests/test_cleanup_fixture_stores.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `inspect_sulmona(session) -> SulmonaSummary` and `cleanup_sulmona(session, expected) -> SulmonaSummary`.
- Exact expected source: 72 records, `2026-04-26` through `2026-07-09`, revenue sum `49488.00`.

- [ ] **Step 1: Write failing dry-run and cleanup tests**

```python
async def test_cleanup_clears_activity_and_profit_items_without_changing_revenue(db_session, seeded_sulmona):
    before = await inspect_sulmona(db_session)
    after = await cleanup_sulmona(db_session, expected=before)
    assert after.record_count == before.record_count == 72
    assert after.revenue_sum == before.revenue_sum == Decimal("49488.00")
    assert after.activity_count == 0
    assert after.profit_item_count == 0
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend; python -m pytest tests/test_cleanup_sulmona.py -q`

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement dry-run-by-default cleanup**

The CLI accepts `--apply` and refuses to mutate unless the store name, count, date range, and revenue sum exactly match expected values. In apply mode it:

1. Sets `activity=NULL` on all Sulmona records.
2. Keeps each record `daily_revenue` unchanged.
3. Sets `income_mode='legacy_total'` and `income_config_version_id=NULL`.
4. Deletes `DailyIncomeItem` rows whose snapshotted/current category name is `日利润`.
5. Archives the `日利润` category if any reference remains; otherwise deletes it.
6. Writes one non-rollbackable admin/system audit describing counts only.
7. Re-runs inspection before commit and rolls back on any mismatch.

- [ ] **Step 4: Test, back up, dry-run, apply, and verify local data**

Run: `cd backend; python -m pytest tests/test_cleanup_sulmona.py -q`

Expected: PASS.

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/backup-local-db.ps1`

Run: `cd backend; python -m app.scripts.cleanup_sulmona`

Expected: dry-run reports 72 records and no mutation.

Run: `cd backend; python -m app.scripts.cleanup_sulmona --apply`

Expected: post-check reports 72 records, the same range and `49488.00`, with zero activity and zero `日利润` items.

- [ ] **Step 5: Commit**

Before committing, run `python -m app.scripts.cleanup_fixture_stores` in dry-run mode. It may target only exact stores `Slow`, `Failed`, and `Healthy`; it must report dependent records, memberships, settings, briefings, alerts, tasks, and audits. Apply removal only after the backup exists and the inspection proves these are fixture-only stores. If any store has unrecognized business records, leave it unchanged and report the conflict instead of guessing. After removal, verify none appear in `/api/stores/accessible` or the active admin store list.

```bash
git add backend/app/scripts/cleanup_sulmona.py backend/app/scripts/cleanup_fixture_stores.py backend/tests/test_cleanup_sulmona.py backend/tests/test_cleanup_fixture_stores.py README.md
git commit -m "data: clean imported and fixture records"
```

---

### Task 8: Add Address Autocomplete and Reverse-Geocoding Adapters

**Files:**
- Create: `backend/app/services/geocoding.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/routes/admin.py`
- Modify: `backend/tests/api/test_admin.py`
- Create: `backend/tests/services/test_geocoding.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `GeocodingProvider.autocomplete(query, bias)`, `reverse(latitude, longitude)`, `GeoapifyProvider`, and `FallbackGeocodingProvider`.
- HTTP: `GET /api/admin/stores/geocode?query=...&latitude=...&longitude=...` and `GET /api/admin/stores/reverse-geocode?latitude=...&longitude=...`.

- [ ] **Step 1: Write failing provider and API tests**

```python
async def test_geoapify_autocomplete_normalizes_full_address(respx_mock):
    provider = GeoapifyProvider(api_key="test-key")
    result = await provider.autocomplete("Via Roma 1 Sulmona", None)
    assert result[0].address
    assert result[0].latitude == Decimal("42.047")


async def test_missing_geoapify_key_falls_back_to_place_search(admin_client, weather_stub):
    response = await admin_client.get("/api/admin/stores/geocode", params={"query": "Sulmona"})
    assert response.status_code == 200
    assert weather_stub.geocode_calls == ["Sulmona"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend; python -m pytest tests/services/test_geocoding.py tests/api/test_admin.py -q`

Expected: FAIL because the adapter is absent.

- [ ] **Step 3: Add optional secret configuration and normalized result type**

```python
class Settings(BaseSettings):
    geoapify_api_key: SecretStr | None = None


@dataclass(frozen=True)
class AddressCandidate:
    address: str
    latitude: Decimal
    longitude: Decimal
    timezone: str | None
    provider: str
```

The key remains backend-only. Geoapify handles debounced autocomplete and reverse geocoding. If absent or unavailable, explicit Open-Meteo search remains available; reverse geocoding may return no address and the UI keeps the typed address.

- [ ] **Step 4: Implement rate/timeout boundaries and normalized endpoints**

Use one `httpx.AsyncClient` per request/provider call, an 8-second timeout, and return an empty list on upstream availability errors. Validate coordinates with existing schema types. Do not proxy arbitrary URLs.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend; python -m pytest tests/services/test_geocoding.py tests/api/test_admin.py -q`

Expected: PASS.

```bash
git add backend/app/services/geocoding.py backend/app/core/config.py backend/app/main.py backend/app/api/routes/admin.py backend/tests/services/test_geocoding.py backend/tests/api/test_admin.py .env.example
git commit -m "feat: add replaceable store geocoding adapters"
```

---

### Task 9: Rebuild the Responsive Application Shell and Persist Store Selection

**Files:**
- Create: `frontend/src/navigation/modules.ts`
- Create: `frontend/src/pages/MorePage.tsx`
- Create: `frontend/src/components/PageState.tsx`
- Modify: `frontend/src/layouts/AppShell.tsx`
- Modify: `frontend/src/stores/StoreProvider.tsx`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/App.test.tsx`
- Create: `frontend/src/layouts/AppShell.test.tsx`
- Create: `frontend/src/stores/StoreProvider.test.tsx`

**Interfaces:**
- Produces: `AppModule`, `visibleModules(user, surface)`, local-storage key `autolava:selected-store:<userId>`, four-item mobile nav, desktop sidebar, and `/more`.

- [ ] **Step 1: Write failing shell and persistence tests**

```tsx
it("renders exactly four mobile destinations", async () => {
  renderAppAt("/");
  const nav = await screen.findByRole("navigation", { name: "移动导航" });
  expect(within(nav).getAllByRole("link")).toHaveLength(4);
  expect(within(nav).getByRole("link", { name: "首页" })).toBeInTheDocument();
  expect(within(nav).getByRole("link", { name: "更多" })).toBeInTheDocument();
});


it("restores the last authorized store and removes a revoked selection", async () => {
  localStorage.setItem("autolava:selected-store:1", "2");
  const { rerenderWithStores } = renderStoreProvider([{ id: 1 }, { id: 2 }]);
  expect(await screen.findByText("selected:2")).toBeInTheDocument();
  rerenderWithStores([{ id: 1 }]);
  expect(await screen.findByText("selected:1")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run frontend tests and verify failure**

Run: `cd frontend; npm test -- src/layouts/AppShell.test.tsx src/stores/StoreProvider.test.tsx`

Expected: FAIL because module navigation and persistence do not exist.

- [ ] **Step 3: Define module metadata and capability-aware visibility**

```tsx
export interface AppModule {
  id: string;
  to: string;
  label: string;
  icon: LucideIcon;
  mobilePrimary: boolean;
  adminOnly?: boolean;
}

export const modules: AppModule[] = [
  { id: "home", to: "/", label: "首页", icon: Home, mobilePrimary: true },
  { id: "ledger", to: "/ledger", label: "记账", icon: BookOpen, mobilePrimary: true },
  { id: "records", to: "/database", label: "记录", icon: Database, mobilePrimary: true },
  { id: "charts", to: "/charts", label: "图表分析", icon: BarChart3, mobilePrimary: false },
  { id: "admin", to: "/admin", label: "管理中心", icon: Settings, mobilePrimary: false, adminOnly: true },
  { id: "more", to: "/more", label: "更多", icon: Menu, mobilePrimary: true },
];
```

- [ ] **Step 4: Implement desktop sidebar, mobile safe area, and More page**

Desktop uses a fixed-width sidebar and main content column. Mobile renders only 首页/记账/记录/更多. `main` receives bottom padding using `calc(var(--mobile-nav-height) + env(safe-area-inset-bottom) + 1rem)`. More contains charts, admin when allowed, account name, and logout.

- [ ] **Step 5: Persist store selection by user**

StoreProvider consumes the authenticated user ID, restores only an ID in the accessible list, defaults to the only/first accessible store, updates localStorage on selection, and removes a revoked ID. Tests must isolate localStorage between cases.

- [ ] **Step 6: Run tests and commit**

Run: `cd frontend; npm test -- src/layouts/AppShell.test.tsx src/stores/StoreProvider.test.tsx src/App.test.tsx`

Expected: PASS.

```bash
git add frontend/src/navigation frontend/src/pages/MorePage.tsx frontend/src/components/PageState.tsx frontend/src/layouts/AppShell.tsx frontend/src/stores/StoreProvider.tsx frontend/src/router.tsx frontend/src/index.css frontend/src/App.test.tsx frontend/src/layouts/AppShell.test.tsx frontend/src/stores/StoreProvider.test.tsx
git commit -m "feat: add responsive modular navigation shell"
```

---

### Task 10: Preserve the Home Layout and Build the Compact Dual-Mode Ledger

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/lib/user-api.ts`
- Create: `frontend/src/components/CollapsibleOptionalFields.tsx`
- Modify: `frontend/src/components/LedgerForm.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`
- Modify: `frontend/src/pages/LedgerPage.tsx`
- Modify: `frontend/src/pages/HomePage.test.tsx`
- Modify: `frontend/src/pages/LedgerPage.test.tsx`

**Interfaces:**
- Consumes: configuration/form metadata and ledger concurrency fields from Task 4.
- Produces: strict homepage content, direct-total/composed form states, optional-field disclosure, and sticky save action.

- [ ] **Step 1: Write failing homepage and mode tests**

```tsx
it("keeps exactly three briefing cards followed by immediate ledger action", async () => {
  renderHomeWithCards([yesterday, today, tomorrow]);
  expect(await screen.findAllByTestId("briefing-card")).toHaveLength(3);
  expect(screen.getByRole("link", { name: "立即记账" })).toHaveAttribute("href", "/ledger");
});


it("shows direct total only when composition is disabled", async () => {
  render(<LedgerForm config={{ enabled: false, version_id: null, items: [] }} onSave={save} />);
  expect(screen.getByLabelText("当日总收入")).toBeEnabled();
  expect(screen.queryByText("收入组成")).not.toBeInTheDocument();
});


it("calculates a read-only total from selected composition items", async () => {
  render(<LedgerForm config={composedConfig} onSave={save} />);
  fireEvent.change(screen.getByLabelText("现金"), { target: { value: "420" } });
  fireEvent.change(screen.getByLabelText("刷卡"), { target: { value: "860" } });
  fireEvent.change(screen.getByLabelText("外卖平台"), { target: { value: "120" } });
  expect(screen.getByText("€1280.00")).toBeInTheDocument();
  expect(screen.queryByLabelText("当日总收入")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd frontend; npm test -- src/pages/HomePage.test.tsx src/pages/LedgerPage.test.tsx`

Expected: FAIL on missing action and dual-mode UI.

- [ ] **Step 3: Add exact TypeScript contracts**

```ts
export interface LedgerFormConfig {
  store_id: number;
  enabled: boolean;
  version_id: number | null;
  version: number;
  items: IncomeConfigItem[];
}

export interface LedgerBody {
  is_open: LedgerStatus;
  daily_revenue: string | null;
  config_version_id: number | null;
  expected_version: number | null;
  wash_count: number | null;
  weather: string | null;
  weather_edited: boolean;
  activity: string | null;
  items: IncomeItemBody[];
}
```

- [ ] **Step 4: Implement the compact form**

Keep date/status and income visible. Put weather plus wash/activity/notes in an accessible disclosure component. Display `仅记录，不计入总收入` on excluded components. In total mode submit no items. In composed mode submit no `daily_revenue`, send the config version and all active item values. Editing sends the record `row_version`.

- [ ] **Step 5: Keep save above the mobile navigation and preserve draft input**

Use a sticky action container within the page flow, not a viewport overlay. Changing optional disclosure state must not unmount and lose values. Warn before navigating away when the form is dirty.

- [ ] **Step 6: Run tests and commit**

Run: `cd frontend; npm test -- src/pages/HomePage.test.tsx src/pages/LedgerPage.test.tsx`

Expected: PASS.

```bash
git add frontend/src/api/types.ts frontend/src/lib/user-api.ts frontend/src/components/CollapsibleOptionalFields.tsx frontend/src/components/LedgerForm.tsx frontend/src/pages/HomePage.tsx frontend/src/pages/LedgerPage.tsx frontend/src/pages/HomePage.test.tsx frontend/src/pages/LedgerPage.test.tsx
git commit -m "feat: streamline daily revenue entry"
```

---

### Task 11: Rebuild Records for Compact Mobile Use and Detailed Desktop Auditing

**Files:**
- Create: `frontend/src/components/MobileRecordTable.tsx`
- Create: `frontend/src/components/DesktopRecordTable.tsx`
- Create: `frontend/src/components/RecordDetail.tsx`
- Create: `frontend/src/components/AuditHistory.tsx`
- Remove: `frontend/src/components/RecordTable.tsx`
- Modify: `backend/app/api/routes/database.py`
- Modify: `backend/app/schemas/database.py`
- Modify: `backend/app/services/export.py`
- Modify: `backend/tests/api/test_database.py`
- Modify: `frontend/src/pages/DatabasePage.tsx`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/pages/DatabasePage.test.tsx`
- Modify: `frontend/tests/responsive.spec.ts`

**Interfaces:**
- Consumes: record snapshots, `row_version`, and paginated `AuditPage`.
- Produces: mobile compact columns, desktop complete columns including creators/updaters, detail drawer/dialog, and on-demand audit pages.

- [ ] **Step 1: Write failing component and responsive tests**

```tsx
it("mobile table exposes only date total status and detail", async () => {
  renderDatabaseAtWidth(390, [record]);
  const headers = screen.getAllByRole("columnheader").map((node) => node.textContent);
  expect(headers).toEqual(["日期", "总收入", "状态", "详情"]);
  expect(screen.queryByRole("button", { name: /删除/ })).not.toBeInTheDocument();
});


it("desktop table includes creator and last editor", async () => {
  renderDatabaseAtWidth(1280, [record]);
  expect(screen.getByRole("columnheader", { name: "记录人" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "最后修改人" })).toBeInTheDocument();
});
```

Playwright must also assert `document.documentElement.scrollWidth === window.innerWidth`, the last page action scrolls above the mobile nav, and clicking detail never changes the root horizontal scroll.

- [ ] **Step 2: Run tests and verify failure**

Run: `cd frontend; npm test -- src/pages/DatabasePage.test.tsx`

Expected: FAIL because the current shared table exposes all columns on mobile.

- [ ] **Step 3: Split record presentation by responsibility**

Use CSS media visibility or a `useMediaQuery` hook with deterministic tests. Mobile table has four columns and opens `RecordDetail`. Desktop table includes date, status, total, wash, weather, components, activity, record creator, last editor, and actions.

Update the database response and Excel export to derive historical component columns from each item's `category_name` snapshot rather than the current category table. A legacy-total record has no invented component cells. Export retains total revenue, record creator, and last editor; filters remain identical between the page and export URL.

- [ ] **Step 4: Move all dangerous actions and audit history into detail**

RecordDetail shows full snapshot and provides edit/delete according to capabilities. AuditHistory requests `record_id`, `page`, and `page_size=10` only when opened. Pruned entries display “历史内容已按保留策略清理” and no rollback button.

- [ ] **Step 5: Pass concurrency versions through edit/delete/rollback**

Edits send `expected_version`; deletes add `?expected_version=<row_version>`; a 409 keeps the dialog open, explains that the record changed, and offers reload.

- [ ] **Step 6: Run unit and browser tests and commit**

Run: `cd frontend; npm test -- src/pages/DatabasePage.test.tsx`

Run: `cd frontend; npm run test:e2e -- responsive.spec.ts`

Expected: PASS with no root overflow or bottom-nav overlap.

```bash
git add backend/app/api/routes/database.py backend/app/schemas/database.py backend/app/services/export.py backend/tests/api/test_database.py frontend/src/components/MobileRecordTable.tsx frontend/src/components/DesktopRecordTable.tsx frontend/src/components/RecordDetail.tsx frontend/src/components/AuditHistory.tsx frontend/src/components/RecordTable.tsx frontend/src/pages/DatabasePage.tsx frontend/src/api/types.ts frontend/src/pages/DatabasePage.test.tsx frontend/tests/responsive.spec.ts
git commit -m "feat: make record browsing mobile friendly"
```

---

### Task 12: Upgrade Analytics to Revenue Trend plus Daily Composition

**Files:**
- Modify: `backend/app/schemas/charts.py`
- Modify: `backend/app/services/analytics.py`
- Modify: `backend/app/api/routes/charts.py`
- Modify: `backend/tests/services/test_analytics.py`
- Modify: `backend/tests/api/test_charts.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/components/ChartPanel.tsx`
- Modify: `frontend/src/pages/ChartsPage.tsx`
- Modify: `frontend/src/components/ChartPanel.test.tsx`
- Modify: `frontend/src/pages/ChartsPage.test.tsx`

**Interfaces:**
- Produces: daily revenue rows with `components`, KPI `average_daily_revenue` and `highest_day`, and four quick-range controls.

- [ ] **Step 1: Write failing backend analytics tests**

```python
async def test_daily_composition_uses_item_snapshots_and_keeps_legacy_total_days(service, seeded_records):
    result = await service.calculate(store_id=1, start=date(2026, 7, 1), end=date(2026, 7, 31), category_ids=[])
    assert result["daily"][0]["revenue"] == "100.00"
    assert result["daily"][0]["components"] == []
    assert result["daily"][1]["components"] == [
        {"category_id": 2, "category_name": "现金", "amount": "40.00", "include_in_total": True}
    ]
```

- [ ] **Step 2: Write failing frontend chart tests**

```tsx
it("offers approved quick ranges and hides composition with fewer than two series", async () => {
  renderCharts(singleCompositionResponse);
  expect(screen.getByRole("button", { name: "本月" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "上月" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "最近30天" })).toBeInTheDocument();
  expect(screen.queryByText("每日收入组成")).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run tests and verify failure**

Run: `cd backend; python -m pytest tests/services/test_analytics.py tests/api/test_charts.py -q`

Run: `cd frontend; npm test -- src/components/ChartPanel.test.tsx src/pages/ChartsPage.test.tsx`

Expected: FAIL on missing daily compositions and quick ranges.

- [ ] **Step 4: Build analytics from record/item snapshots**

Legacy total records contribute to revenue trend and KPIs only. Composed records expose their snapshotted item names and include flags. Never use the current category name to rewrite history. Compute average daily revenue over recorded days and highest day with deterministic date tie-breaking.

- [ ] **Step 5: Render trend and conditional stacked composition**

Always show total trend when data exists. Show stacked daily composition only when at least two active component series occur in the selected range. Keep date inputs for custom ranges and add the approved quick buttons.

- [ ] **Step 6: Run focused tests and commit**

Run: `cd backend; python -m pytest tests/services/test_analytics.py tests/api/test_charts.py -q`

Run: `cd frontend; npm test -- src/components/ChartPanel.test.tsx src/pages/ChartsPage.test.tsx`

Expected: PASS.

```bash
git add backend/app/schemas/charts.py backend/app/services/analytics.py backend/app/api/routes/charts.py backend/tests/services/test_analytics.py backend/tests/api/test_charts.py frontend/src/api/types.ts frontend/src/components/ChartPanel.tsx frontend/src/pages/ChartsPage.tsx frontend/src/components/ChartPanel.test.tsx frontend/src/pages/ChartsPage.test.tsx
git commit -m "feat: analyze revenue trends and composition"
```

---

### Task 13: Split the Admin Center and Add Map-Style Store Editing

**Files:**
- Create: `frontend/src/pages/admin/AdminLayout.tsx`
- Create: `frontend/src/pages/admin/UsersAdmin.tsx`
- Create: `frontend/src/pages/admin/StoresAdmin.tsx`
- Create: `frontend/src/pages/admin/IncomeConfigAdmin.tsx`
- Create: `frontend/src/pages/admin/SystemAdmin.tsx`
- Create: `frontend/src/pages/admin/AuditAdmin.tsx`
- Create: `frontend/src/components/AddressPicker.tsx`
- Create: `frontend/src/components/StoreMap.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `.env.example`
- Modify: `frontend/src/pages/AdminPage.test.tsx`
- Create: `frontend/src/components/AddressPicker.test.tsx`

**Interfaces:**
- Consumes: income configuration, archive, restore, admin safety, and geocoding APIs.
- Produces: focused admin routes, address suggestions, current position, draggable pin, reverse geocoding, and hidden coordinate storage.

- [ ] **Step 1: Install pinned Leaflet dependencies**

Run: `cd frontend; npm install leaflet@1.9.4 @types/leaflet@1.9.20`

Expected: package and lockfile updated; no unrelated dependency upgrades.

- [ ] **Step 2: Write failing admin organization and address tests**

```tsx
it("organizes management into approved sections", async () => {
  renderAdmin();
  expect(await screen.findByRole("link", { name: "店铺" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "用户与权限" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "收入组成" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "系统设置" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "审计记录" })).toBeInTheDocument();
});


it("selects an address suggestion without exposing coordinate inputs", async () => {
  render(<AddressPicker value={emptyLocation} onChange={change} />);
  fireEvent.change(screen.getByLabelText("店铺地址"), { target: { value: "Via Roma" } });
  fireEvent.click(await screen.findByRole("option", { name: /Via Roma 1/ }));
  expect(screen.queryByLabelText("纬度")).not.toBeInTheDocument();
  expect(change).toHaveBeenCalledWith(expect.objectContaining({ latitude: "42.047000" }));
});
```

- [ ] **Step 3: Run tests and verify failure**

Run: `cd frontend; npm test -- src/pages/AdminPage.test.tsx src/components/AddressPicker.test.tsx`

Expected: FAIL because pages and address picker do not exist.

- [ ] **Step 4: Split admin sections into focused routes**

Use `/admin/stores`, `/admin/users`, `/admin/income`, `/admin/system`, and `/admin/audit`, with `/admin` redirecting to stores. Keep query keys close to each domain module. User deactivation buttons reflect backend safety errors and disable the current account action proactively.

- [ ] **Step 5: Build AddressPicker and StoreMap**

AddressPicker debounces autocomplete by 350 ms when the backend reports Geoapify availability; fallback mode uses an explicit “搜索地址” action to avoid misusing public geocoding APIs. “使用当前位置” uses `navigator.geolocation`. StoreMap initializes Leaflet, adds an attributed configurable tile layer, displays one draggable marker, and calls reverse geocoding after drag end. The form stores coordinates in state but renders no coordinate inputs.

Use `VITE_MAP_TILE_URL=https://tile.openstreetmap.org/{z}/{x}/{y}.png` as the development default, expose it in `.env.example`, and render the required visible `© OpenStreetMap contributors` attribution. Do not preload or cache-bust tiles.

- [ ] **Step 6: Build income composition list management**

Display active and archived lists separately. Allow name, sort order, active, and include-in-total editing. Show formula preview. Archive hides an item; restore returns it to the draft; permanent delete appears only for an unused item and requires confirmation. Show version history with at most the retained versions and a restore action that creates a new version.

- [ ] **Step 7: Run tests and commit**

Run: `cd frontend; npm test -- src/pages/AdminPage.test.tsx src/components/AddressPicker.test.tsx`

Run: `cd frontend; npm run build`

Expected: PASS.

```bash
git add .env.example frontend/package.json frontend/package-lock.json frontend/src/pages/admin frontend/src/pages/AdminPage.tsx frontend/src/components/AddressPicker.tsx frontend/src/components/StoreMap.tsx frontend/src/router.tsx frontend/src/api/types.ts frontend/src/pages/AdminPage.test.tsx frontend/src/components/AddressPicker.test.tsx
git commit -m "feat: organize administration and map store addresses"
```

---

### Task 14: Finish UX States, Branding, Responsive Regression Coverage, and Documentation

**Files:**
- Modify: `frontend/index.html`
- Create: `frontend/public/favicon.svg`
- Modify: `frontend/src/components/PageState.tsx`
- Modify: `frontend/src/index.css`
- Modify: `frontend/tests/responsive.spec.ts`
- Create: `frontend/tests/core-flows.spec.ts`
- Modify: `frontend/playwright.config.ts`
- Modify: `README.md`
- Modify: `docs/superpowers/2026-07-13-phase-1-task-6-handoff.md`

**Interfaces:**
- Produces: consistent loading/empty/error/success states, favicon/title, realistic mobile and desktop end-to-end checks, and updated operator documentation.

- [ ] **Step 1: Add failing browser assertions for practical usability**

```ts
test("mobile core flow never hides the last action behind navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await page.goto("/ledger");
  const save = page.getByRole("button", { name: "保存今日记录" });
  await save.scrollIntoViewIfNeeded();
  const saveBox = await save.boundingBox();
  const navBox = await page.getByRole("navigation", { name: "移动导航" }).boundingBox();
  expect(saveBox!.y + saveBox!.height).toBeLessThanOrEqual(navBox!.y);
});
```

Also cover: four mobile links within 390 px; desktop sidebar visible; homepage three cards plus action; mobile record table four columns; detail actions reachable; direct-total and composed saves; store persistence after reload; admin self-deactivation rejected; chart quick ranges; map failure leaves address editable.

- [ ] **Step 2: Run browser tests and verify failure**

Run: `cd frontend; npm run test:e2e -- responsive.spec.ts core-flows.spec.ts`

Expected: FAIL until final layout/state changes are complete.

- [ ] **Step 3: Normalize page states and branding**

Use PageState for loading, empty, recoverable error, and permission states. Add a local SVG favicon and Chinese title. Make success messages `role=status`, errors `role=alert`, and preserve actionable retry buttons.

- [ ] **Step 4: Update documentation**

README must document runtime/test database separation, backup command, local launcher, optional `AUTOLAVA_GEOAPIFY_API_KEY`, OpenStreetMap attribution, retention rules, Sulmona cleanup command, and the fact that no Excel-import UI exists. Handoff documentation must list the new routes and migration revision.

- [ ] **Step 5: Run complete non-destructive verification**

First verify the effective backend test URL is `autolava_test` and the runtime URL is not. Then run:

```bash
cd backend
python -m ruff check app tests
python -m pytest -q
```

Expected: all backend lint and tests PASS against `autolava_test` only.

```bash
cd frontend
npm test
npm run build
npm run test:e2e
```

Expected: all frontend unit tests, TypeScript build, Vite build, and browser tests PASS.

- [ ] **Step 6: Run migration and local launcher smoke checks**

Back up `autolava_local`, apply Alembic head, run Sulmona cleanup in dry-run mode, start the local system using `scripts/start-local.ps1`, and verify `/api/health`, login page, authenticated homepage, ledger, records, charts, and admin routes. Stop the launcher cleanly afterward.

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html frontend/public/favicon.svg frontend/src/components/PageState.tsx frontend/src/index.css frontend/tests frontend/playwright.config.ts README.md docs/superpowers/2026-07-13-phase-1-task-6-handoff.md
git commit -m "test: verify redesigned core flows"
```

---

### Task 15: Final Requirement Audit and Branch Completion

**Files:**
- Modify only if verification exposes a documented defect.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: evidence that every approved requirement is implemented, a clean worktree, and a branch ready for the finishing workflow.

- [ ] **Step 1: Audit the implementation against every design section**

Create a local checklist from sections 3–15 of `docs/superpowers/specs/2026-07-15-autolava-usability-foundation-redesign.md`. For each requirement, record the implementing file and verifying test. A missing mapping is a defect and must be fixed before completion.

- [ ] **Step 2: Re-run fresh full verification**

Run backend lint/tests, frontend unit/build/e2e, `git diff --check`, `git status --short`, and the local launcher smoke check again after the final fix. Do not reuse output from Task 14.

Expected: zero lint errors, zero test failures, successful builds, successful smoke checks, and no uncommitted files.

- [ ] **Step 3: Invoke the required finishing skill**

Announce and use `superpowers:finishing-a-development-branch`. Present the verified integration choices required by that skill; do not merge, push, or delete the worktree without the user's selected option.
