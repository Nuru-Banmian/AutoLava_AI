# AutoLava SQLite Runtime Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing MySQL runtime with a clean SQLite baseline, simplify Phase 1 to integer-money current-state behavior, and deploy only one API plus one Web service on the 2-core/2-GB family server.

**Architecture:** A single FastAPI/Uvicorn worker owns one persistent SQLite database configured for WAL, foreign keys, and a 10-second busy timeout. Nginx serves a prebuilt frontend; the API also runs the existing weather/briefing jobs and one lightweight daily SQLite backup task. Audit history, rollback, income configuration versions, row-version conflicts, token state, Phase 2, MySQL, and in-app restore are removed rather than emulated.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, aiosqlite, Alembic, Pydantic, React, TypeScript, TanStack Query, Vitest, Playwright, Docker Compose, Nginx.

## Global Constraints

- Do not migrate or back up the old MySQL data; the production MySQL container and volume are intentionally destroyed during cutover.
- Store `daily_revenue` and income item `amount` as non-negative integers; reject decimal input and sum only items where `include_in_total=true`.
- Preserve historical business-day records and per-record income-item snapshots, but remove audit history, rollback, configuration-version history, and `row_version` conflict handling.
- Use one API process and one Uvicorn worker; do not add Redis, Celery, RabbitMQ, PostgreSQL, an Agent worker, an Agent table, or an empty future API.
- Use a stateless 24-hour JWT HttpOnly cookie; do not persist refresh tokens, remember tokens, or server sessions.
- Create one verified SQLite online backup per day at 03:00 server time, catch up on startup when the current day has no valid backup, and retain only three calendar days.
- Do not implement an application restore route, UI, command, or script.
- Do not set container memory limits or add a permanent load-test/monitoring service.
- Keep Phase 3 and Phase 4 as documentation-only considerations; delete Phase 2 without renumbering phases 1, 3, and 4.
- Preserve unrelated working-tree changes. `README.md`, `.superpowers/sdd/progress.md`, the two untracked cleanup scripts/tests, and the untracked handoff document predate this plan; inspect and merge overlapping lines instead of replacing those files wholesale.

---

## File Structure and Responsibility Map

### SQLite foundation

- `backend/app/core/config.py`: database path, JWT, cookie, backup path/timezone settings.
- `backend/app/core/database.py`: SQLite URL creation, parent-directory creation, async engine/session, connection PRAGMAs.
- `backend/tests/conftest.py`: one disposable file-backed SQLite database for backend tests.
- `backend/tests/test_sqlite_database.py`: SQLite configuration and real-connection contract.

### Final schema

- `backend/app/models/identity.py`: users, stores, memberships, and current `income_items_enabled` store setting.
- `backend/app/models/ledger.py`: integer-money daily records and immutable item snapshots.
- `backend/app/models/operations.py`: briefings, seven-day task logs, and alerts.
- `backend/alembic/versions/0001_sqlite_baseline.py`: the only supported clean-database migration.
- `backend/tests/test_schema.py`: exact final table/column/constraint contract.
- `backend/tests/test_sqlite_migration.py`: upgrade a blank SQLite file to head and inspect it.

### Current-state backend

- `backend/app/services/income_config.py`: replace the current store configuration without versions.
- `backend/app/services/ledger.py`: create/overwrite/delete current daily data with integer amounts.
- `backend/app/services/record_payload.py`: serialize daily records and item snapshots without audit semantics.
- `backend/app/services/analytics.py`, `backend/app/services/export.py`, `backend/app/services/briefing.py`: integer-money reporting, export, and SQLite briefing upsert.
- `backend/app/api/routes/admin.py`, `income_config.py`, `ledger.py`, `database.py`, `charts.py`, `dashboard.py`: simplified API surface.

### Authentication

- `backend/app/core/security.py`, `backend/app/api/routes/auth.py`, `backend/app/schemas/auth.py`: fixed 24-hour stateless JWT login.
- `frontend/src/auth/AuthProvider.tsx`, `frontend/src/pages/LoginPage.tsx`: no remember option or refresh state.
- `frontend/nginx.conf`: 1-MB login rate-limit zone at 10 requests/minute with burst 10.

### Frontend current-state UI

- `frontend/src/api/types.ts`: integer money and removal of audit/version fields.
- `frontend/src/lib/user-api.ts`: integer validation/formatting and query invalidation keys.
- `frontend/src/components/LedgerForm.tsx`, `LedgerDatePicker.tsx`, `MonthCalendar.tsx`: integer entry, saved baseline, old-record snapshot fill, month markers.
- `frontend/src/pages/LedgerPage.tsx`: direct overwrite and no version/config conflict flow.
- `frontend/src/components/RecordManagementDialogs.tsx`, `frontend/src/pages/BusinessRecordsPage.tsx`: permanent delete only; no history or rollback.
- Reporting components/pages: display whole-euro values consistently.

### Backup and operations

- `backend/app/services/sqlite_backup.py`: online backup, integrity check, atomic promotion, three-day pruning.
- `backend/app/services/scheduler.py`: exact daily scheduling plus serial SQLite write-back for existing background work.
- `backend/app/services/operations_retention.py`: task-log and resolved-alert seven-day cleanup.
- `backend/app/main.py`: lifecycle ownership for weather, retention, and backup schedulers.

### Runtime and documentation

- `compose.yaml`, `.env.example`, `backend/Dockerfile`, `frontend/Dockerfile.prebuilt`, `.github/workflows/ci.yml`: two-service production and SQLite CI.
- `scripts/start-local.ps1`, `start-autolava.bat`: deliberately simple laptop launcher.
- `README.md`: SQLite development, prebuilt deployment, backup behavior, and manual replacement warning.
- `docs/superpowers/plans/2026-07-13-autolava-ai-roadmap.md`: phases 1, 3, and 4 only.
- Phase 3/4 plan files: future SQLite/2-GB constraints, explicitly not current implementation.

---

### Task 1: Establish the SQLite runtime and disposable test database

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/database.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/test_sqlite_database.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `Settings.database_path: Path`, `Settings.backup_directory: Path`, `sqlite_url(path: Path) -> URL`, `engine`, `async_session_factory`, and real connection PRAGMAs.
- Consumes: no later-task interface.

- [ ] **Step 1: Write failing settings and PRAGMA tests**

Create `backend/tests/test_sqlite_database.py` with tests that require a path-only configuration and inspect a live connection:

```python
from pathlib import Path

from sqlalchemy import text

from app.core.config import Settings
from app.core.database import engine, sqlite_url


def test_sqlite_url_uses_aiosqlite_and_absolute_path(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "autolava.sqlite3")
    assert url.drivername == "sqlite+aiosqlite"
    assert Path(url.database or "").is_absolute()


def test_settings_use_paths_without_database_credentials(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "runtime.sqlite3",
        backup_directory=tmp_path / "backups",
    )
    assert settings.database_path.name == "runtime.sqlite3"
    assert settings.backup_directory.name == "backups"


async def test_live_connections_enable_required_pragmas() -> None:
    async with engine.connect() as connection:
        foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))
        busy_timeout = await connection.scalar(text("PRAGMA busy_timeout"))
        journal_mode = await connection.scalar(text("PRAGMA journal_mode"))
        synchronous = await connection.scalar(text("PRAGMA synchronous"))
    assert foreign_keys == 1
    assert busy_timeout == 10_000
    assert str(journal_mode).lower() == "wal"
    assert synchronous == 1
```

- [ ] **Step 2: Run the focused tests and confirm the MySQL defaults fail them**

Run from `backend`: `pytest tests/test_sqlite_database.py -q`

Expected: FAIL because `database_path`, `backup_directory`, and `sqlite_url` do not exist and the engine still uses MySQL.

- [ ] **Step 3: Replace database dependencies and settings**

In `backend/pyproject.toml`, replace `asyncmy` with `aiosqlite` and remove the currently unused `apscheduler` dependency. In `config.py`, use path settings and keep production validation limited to JWT/cookie safety:

```python
from pathlib import Path

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOLAVA_", env_file=".env")

    environment: str = "development"
    database_path: Path = Path("../.autolava-local/autolava.sqlite3")
    backup_directory: Path = Path("../.autolava-local/backups")
    maintenance_timezone: str = "Europe/Rome"
    jwt_secret: SecretStr = SecretStr("development-only-secret")
    bootstrap_username: str = ""
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
```

Remove the production database-password checks completely. Retain the random JWT-secret requirement and reject `database_path` values equal to `:memory:` in production.

- [ ] **Step 4: Build the SQLite engine and connection contract**

Replace `backend/app/core/database.py` with a path-owned engine. The connection listener must execute all four PRAGMAs and no network pool options:

```python
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


def sqlite_url(path: Path) -> URL:
    return URL.create("sqlite+aiosqlite", database=str(path.resolve()))


settings = get_settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
engine = create_async_engine(sqlite_url(settings.database_path))


@event.listens_for(engine.sync_engine, "connect")
def configure_sqlite(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
```

- [ ] **Step 5: Convert the test harness to one disposable file-backed SQLite database**

At the top of `backend/tests/conftest.py`, before importing application modules, create a session-owned temporary directory, set `AUTOLAVA_DATABASE_PATH`, and remove the MySQL dialect/name guard. Add a session fixture that creates and drops `Base.metadata`; retain per-test table clearing and transaction rollback. Do not use `:memory:` because concurrency and WAL tests require multiple real connections.

Add `.autolava-test/` to `.gitignore` if the fixture uses a repository-local fallback; the normal path must use `tempfile.TemporaryDirectory`.

- [ ] **Step 6: Run SQLite foundation tests**

Run from `backend`: `pytest tests/test_sqlite_database.py tests/test_schema.py -q`

Expected: PASS. Existing domain tests may still fail because MySQL-specific services and old concurrency assumptions are removed in later tasks.

- [ ] **Step 7: Commit the SQLite foundation**

```bash
git add backend/pyproject.toml backend/app/core/config.py backend/app/core/database.py backend/tests/conftest.py backend/tests/test_sqlite_database.py .gitignore
git commit -m "refactor: establish sqlite runtime"
```

---

### Task 2: Replace the migration chain with the final simplified SQLite schema

**Files:**
- Delete: `backend/alembic/versions/0001_phase_1.py`
- Delete: `backend/alembic/versions/0002_structural_rollback.py`
- Delete: `backend/alembic/versions/0003_audit_rollbackable.py`
- Delete: `backend/alembic/versions/0004_usability_foundation.py`
- Delete: `backend/alembic/versions/0005_structured_dashboard_cards.py`
- Delete: `backend/alembic/versions/0006_timestamp_contracts.py`
- Create: `backend/alembic/versions/0001_sqlite_baseline.py`
- Modify: `backend/alembic/env.py`
- Modify: `backend/app/models/identity.py`
- Modify: `backend/app/models/ledger.py`
- Modify: `backend/app/models/operations.py`
- Modify: `backend/app/models/__init__.py`
- Delete: `backend/app/models/audit.py`
- Delete: `backend/app/models/income_config.py`
- Modify: `backend/tests/test_schema.py`
- Create: `backend/tests/test_sqlite_migration.py`

**Interfaces:**
- Produces: final nine-table model, `Store.income_items_enabled: bool`, integer `StoreDailyRecord.daily_revenue`, integer `DailyIncomeItem.amount`.
- Consumes: `sqlite_url` from Task 1.

- [ ] **Step 1: Replace schema tests with the exact final contract**

Update `backend/tests/test_schema.py` to require exactly these tables:

```python
def test_final_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "stores",
        "store_members",
        "income_categories",
        "store_daily_records",
        "daily_income_items",
        "daily_briefings",
        "scheduled_task_logs",
        "system_alerts",
    }
```

Add assertions that `users` has no `remember_token`, `stores` has `income_items_enabled`, `store_daily_records` has neither `row_version` nor `income_config_version_id`, and the two money columns compile as `INTEGER` on SQLite. Retain the store-member and store/date uniqueness assertions.

- [ ] **Step 2: Add a blank-file migration test**

Create `backend/tests/test_sqlite_migration.py` that runs `python -m alembic upgrade head` in a subprocess with `AUTOLAVA_DATABASE_PATH` pointing at `tmp_path / "migration.sqlite3"`, then uses `sqlite3` to assert the nine table names, the unique `(store_id, date)` index, and `PRAGMA foreign_key_check` returning an empty list.

- [ ] **Step 3: Run schema and migration tests to verify failure**

Run from `backend`: `pytest tests/test_schema.py tests/test_sqlite_migration.py -q`

Expected: FAIL because audit/config-version/store-setting tables and fields still exist, and migration `0004` contains MySQL-only SQL.

- [ ] **Step 4: Simplify the ORM models**

Make these exact model changes:

- Remove `User.remember_token`.
- Add `Store.income_items_enabled = mapped_column(Boolean, default=False)`.
- Delete `StoreSetting`.
- Keep `StoreDailyRecord.income_mode` so old days retain direct-total versus composed behavior.
- Change `StoreDailyRecord.daily_revenue` to `mapped_column(Integer, default=0)`.
- Remove `income_config_version_id` and `row_version`.
- Change `DailyIncomeItem.amount` to `mapped_column(Integer, default=0)`.
- Keep `category_name`, `include_in_total`, and `sort_order` snapshots.
- Delete audit and income-config-version model modules and imports.

- [ ] **Step 5: Generate and normalize one SQLite baseline migration**

Delete all six old migration files. Generate one revision against a blank SQLite file:

Run from `backend`: `python -m alembic revision --autogenerate -m "sqlite baseline"`

Rename it to `0001_sqlite_baseline.py`, keep one `down_revision = None`, and inspect it to ensure it creates only the nine final tables. Replace generated database-specific defaults with SQLite-compatible `sa.func.current_timestamp()` or explicit constant defaults. The downgrade must drop the nine tables in reverse foreign-key order.

- [ ] **Step 6: Run schema and migration verification**

Run from `backend`: `pytest tests/test_schema.py tests/test_sqlite_migration.py tests/test_sqlite_database.py -q`

Expected: PASS with no MySQL server.

- [ ] **Step 7: Commit the clean baseline**

```bash
git add backend/alembic backend/app/models backend/tests/test_schema.py backend/tests/test_sqlite_migration.py
git commit -m "refactor: rebaseline simplified sqlite schema"
```

---

### Task 3: Remove audit, rollback, retention snapshots, and configuration versions from the backend

**Files:**
- Delete: `backend/app/services/audit.py`
- Delete: `backend/app/services/rollback.py`
- Delete: `backend/app/services/retention.py`
- Create: `backend/app/services/record_payload.py`
- Rewrite: `backend/app/services/income_config.py`
- Modify: `backend/app/api/routes/admin.py`
- Modify: `backend/app/api/routes/income_config.py`
- Modify: `backend/app/api/routes/user_income_config.py`
- Modify: `backend/app/api/routes/database.py`
- Modify: `backend/app/services/access.py`
- Modify: `backend/app/schemas/income_config.py`
- Modify: `backend/app/schemas/database.py`
- Delete: `backend/tests/services/test_rollback.py`
- Delete: `backend/tests/services/test_retention.py`
- Modify: `backend/tests/services/test_income_config.py`
- Modify: `backend/tests/api/test_income_config.py`
- Modify: `backend/tests/api/test_admin.py`
- Modify: `backend/tests/api/test_database.py`

**Interfaces:**
- Produces: `record_payload(record: StoreDailyRecord) -> dict[str, Any]`, `IncomeConfigService.current(store_id)`, `IncomeConfigService.replace(store_id, body)`, current config response without version fields.
- Consumes: final Store/IncomeCategory/StoreDailyRecord models from Task 2.

- [ ] **Step 1: Write failing current-config and no-history API tests**

Update income-config tests to assert the response shape is:

```python
{
    "store_id": store.id,
    "enabled": True,
    "formula": "营业额 = 现金；“代收款”只记录，不计入营业额",
    "items": [
        {
            "id": cash.id,
            "store_id": store.id,
            "name": "现金",
            "include_in_total": True,
            "is_active": True,
            "sort_order": 0,
            "archived_at": None,
        },
        {
            "id": agency.id,
            "store_id": store.id,
            "name": "代收款",
            "include_in_total": False,
            "is_active": True,
            "sort_order": 1,
            "archived_at": None,
        },
    ],
}
```

Add route-contract assertions that `/api/database/{store_id}/history`, `/rollback`, `/api/admin/users/{user_id}/operations`, and income-config version/restore endpoints return 404 because the routes no longer exist.

- [ ] **Step 2: Run the focused tests and confirm old version/audit behavior fails**

Run from `backend`: `pytest tests/services/test_income_config.py tests/api/test_income_config.py tests/api/test_admin.py tests/api/test_database.py -q`

Expected: FAIL because response schemas still expose versions and history/rollback routes still exist.

- [ ] **Step 3: Move record serialization out of the audit domain**

Create `record_payload.py` by moving the existing `record_snapshot` serialization logic and renaming it `record_payload`. Its output must omit `row_version` and `income_config_version_id`, retain integer money, include `income_mode`, weather fields, actors/timestamps, and sorted item snapshots. Replace all non-deleted imports of `record_snapshot` with `record_payload`.

- [ ] **Step 4: Implement one current income configuration**

Rewrite `IncomeConfigService` around `Store.income_items_enabled` and `IncomeCategory` only. `replace()` must:

1. Load the store or return 404.
2. Reject duplicate IDs and case-insensitive duplicate names.
3. Reject category IDs owned by another store.
4. Update existing categories in submitted order.
5. Create submitted items with `category_id=None`.
6. Archive active categories omitted from the submitted configuration.
7. Set `store.income_items_enabled = body.enabled`.
8. Flush and return the current response; do not create an audit or version row.

Define response models without `version_id`, `version`, or `created_at`. Keep archive, restore, and permanent-delete-current-if-unused endpoints; used categories remain archived so daily item snapshots and foreign keys remain valid.

- [ ] **Step 5: Remove audit and version routes/services**

Delete rollback/history schemas and routes, user-operation history, audit payload helpers, recalculation audits, audit-based deletion checks, and the `audit.view` capability. Alerts and task logs remain admin-only through the existing admin capability dependency. Remove `StoreSetting` creation/deletion and `standard_work_hours` payloads from admin store operations.

For hard user deletion, check only real references in `StoreDailyRecord.created_by`, `updated_by`, and current configuration ownership that remains in the final schema. For store deletion, keep archive behavior when business records exist and hard-delete only unused stores.

- [ ] **Step 6: Remove obsolete tests and run current-state backend tests**

Delete rollback/retention test modules and remove audit/version assertions from admin/database tests. Run:

Run from `backend`: `pytest tests/services/test_income_config.py tests/api/test_income_config.py tests/api/test_admin.py tests/api/test_database.py -q`

Expected: PASS. Do not stage the pre-existing untracked cleanup scripts/tests in this commit; if they import deleted models, leave them user-owned and report the compatibility issue before later integration.

- [ ] **Step 7: Commit backend history removal**

```bash
git add backend/app/services backend/app/api/routes backend/app/schemas backend/tests/services backend/tests/api
git commit -m "refactor: remove history and config versions"
```

---

### Task 4: Convert ledger, reporting, briefing, and exports to integer current-state behavior

**Files:**
- Modify: `backend/app/schemas/ledger.py`
- Modify: `backend/app/schemas/charts.py`
- Rewrite: `backend/app/services/ledger.py`
- Modify: `backend/app/services/analytics.py`
- Modify: `backend/app/services/export.py`
- Modify: `backend/app/services/briefing.py`
- Modify: `backend/app/services/scheduler.py`
- Modify: `backend/app/api/routes/ledger.py`
- Modify: `backend/app/api/routes/database.py`
- Modify: `backend/app/api/routes/charts.py`
- Modify: `backend/app/api/routes/dashboard.py`
- Modify: `backend/tests/services/test_ledger.py`
- Modify: `backend/tests/services/test_analytics.py`
- Modify: `backend/tests/services/test_briefing.py`
- Modify: `backend/tests/services/test_scheduler.py`
- Modify: `backend/tests/api/test_ledger.py`
- Modify: `backend/tests/api/test_charts.py`
- Modify: `backend/tests/api/test_dashboard.py`
- Modify: `backend/tests/api/test_database.py`

**Interfaces:**
- Produces: integer `LedgerBody`, direct overwrite `LedgerService.upsert`, integer analytics/briefing/export payloads.
- Consumes: `record_payload` and current income configuration from Task 3.

- [ ] **Step 1: Write failing integer and snapshot tests**

Add tests with these exact behaviors:

```python
async def test_composed_total_sums_only_included_integer_items(ledger_context) -> None:
    result = await LedgerService(ledger_context.session).upsert(
        store=ledger_context.store,
        record_date=ledger_context.today,
        payload={
            "is_open": "营业",
            "daily_revenue": None,
            "wash_count": 3,
            "weather": "晴",
            "weather_edited": False,
            "activity": None,
            "items": [
                {"category_id": ledger_context.cash.id, "amount": 100},
                {"category_id": ledger_context.agency.id, "amount": 50},
            ],
        },
        actor=ledger_context.user,
    )
    assert result.record.daily_revenue == 100
    assert [item.amount for item in result.record.items] == [100, 50]
```

Add request tests proving `1.5` and `"1.00"` receive 422, a second PUT overwrites without `overwrite=true` or `expected_version`, and old item names/include flags/order remain unchanged after current category edits.

- [ ] **Step 2: Run focused tests and confirm decimal/version behavior fails**

Run from `backend`: `pytest tests/services/test_ledger.py tests/api/test_ledger.py tests/services/test_analytics.py tests/api/test_charts.py -q`

Expected: FAIL because Pydantic accepts decimals, ledger expects config/row versions, and reports format two decimal places.

- [ ] **Step 3: Replace ledger validation and persistence**

Use `Annotated[int, Field(strict=True, ge=0, le=9_999_999_999)]` for direct and item amounts so JSON strings and floats are rejected. Remove `config_version_id`, `expected_version`, `overwrite`, MySQL row locking, audit creation, and Decimal quantization.

For new records, use `store.income_items_enabled` to select `composed` or `legacy_total`. For existing records, retain the record's `income_mode`. In composed mode, require every active current category exactly once for a new record, and require every existing snapshot category exactly once for an old record. Sum only included items. A rest day writes zero to all amounts.

On every successful update, replace child items from the record snapshot definitions, commit, reload the canonical record, and return it. Use one module-level `asyncio.Lock` to serialize ledger writes inside the single API process so two same-day creates cannot produce a duplicate row; acquire it after external weather lookup and release it immediately after commit/rollback.

- [ ] **Step 4: Convert aggregate and presentation payloads to integers**

Remove `:.2f` money formatting and Decimal string responses across analytics, charts, dashboard, database summaries, and exports. JSON responses use integers. Excel money cells use numeric integers with format `€#,##0`. Average values that can be fractional must be rounded to the nearest whole euro using one documented rule: `ROUND_HALF_UP` in Python before serialization.

Replace MySQL briefing upsert with SQLite conflict update using this exact mapping, then reload the card normally without `with_for_update`:

```python
statement = sqlite_insert(DailyBriefing).values(**values)
statement = statement.on_conflict_do_update(
    index_elements=["store_id", "card_type"],
    set_={
        "content": statement.excluded.content,
        "payload": statement.excluded.payload,
        "generated_at": statement.excluded.generated_at,
        "timestamp_contract": statement.excluded.timestamp_contract,
    },
)
await self.session.execute(statement)
```

- [ ] **Step 5: Serialize background SQLite writes**

Keep weather network calls concurrent, then write each store result in store-ID order with a fresh short session. Re-read `weather_edited` after the network wait and before applying automatic weather. Set background store write concurrency to one; task discovery and external weather calls may remain concurrent.

- [ ] **Step 6: Run ledger/reporting/briefing tests**

Run from `backend`: `pytest tests/services/test_ledger.py tests/api/test_ledger.py tests/services/test_analytics.py tests/api/test_charts.py tests/services/test_briefing.py tests/services/test_scheduler.py tests/api/test_dashboard.py tests/api/test_database.py -q`

Expected: PASS using integer money and no MySQL guard.

- [ ] **Step 7: Commit integer current-state backend**

```bash
git add backend/app/schemas/ledger.py backend/app/schemas/charts.py backend/app/services/ledger.py backend/app/services/analytics.py backend/app/services/export.py backend/app/services/briefing.py backend/app/services/scheduler.py backend/app/api/routes/ledger.py backend/app/api/routes/database.py backend/app/api/routes/charts.py backend/app/api/routes/dashboard.py backend/tests/services/test_ledger.py backend/tests/services/test_analytics.py backend/tests/services/test_briefing.py backend/tests/services/test_scheduler.py backend/tests/api/test_ledger.py backend/tests/api/test_charts.py backend/tests/api/test_dashboard.py backend/tests/api/test_database.py
git commit -m "refactor: use integer current-state ledger"
```

---

### Task 5: Simplify authentication and login throttling

**Files:**
- Modify: `backend/app/schemas/auth.py`
- Modify: `backend/app/core/security.py`
- Modify: `backend/app/api/routes/auth.py`
- Modify: `backend/app/scripts/create_admin.py`
- Modify: `backend/tests/api/test_auth.py`
- Modify: `backend/tests/test_create_admin.py`
- Modify: `frontend/src/auth/AuthProvider.tsx`
- Modify: `frontend/src/pages/LoginPage.tsx`
- Modify: `frontend/src/auth/AuthProvider.test.tsx`
- Modify: `frontend/src/pages/LoginPage.test.tsx`
- Modify: `frontend/nginx.conf`
- Modify: `backend/tests/test_deployment_config.py`

**Interfaces:**
- Produces: `create_access_token(user_id: int) -> tuple[str, int]` with exactly 86,400 seconds, login body `{username, password}`.
- Consumes: `User` without `remember_token` from Task 2.

- [ ] **Step 1: Write failing fixed-cookie and no-remember tests**

Assert the OpenAPI login schema has no `remember`, the cookie has `Max-Age=86400`, admin bootstrap inserts no token field, and the login page has no “记住我” checkbox. Retain password hashing, inactive-user, logout, long-password, and login timing tests. Delete tests whose only purpose is concurrent password row locking.

- [ ] **Step 2: Run focused auth tests**

Run from `backend`: `pytest tests/api/test_auth.py tests/test_create_admin.py tests/test_deployment_config.py -q`

Run from `frontend`: `npm test -- AuthProvider LoginPage`

Expected: FAIL because the remember field and variable max-age still exist and Nginx reserves 10 MB.

- [ ] **Step 3: Implement stateless 24-hour login**

Change the security signature and constant:

```python
ACCESS_TOKEN_SECONDS = 24 * 60 * 60


def create_access_token(user_id: int) -> tuple[str, int]:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(seconds=ACCESS_TOKEN_SECONDS),
    }
    secret = get_settings().jwt_secret.get_secret_value()
    return jwt.encode(payload, secret, algorithm="HS256"), ACCESS_TOKEN_SECONDS
```

Remove `remember` from Pydantic, frontend input types, form state, and request JSON. `create_admin` uses SQLite `insert(User).on_conflict_do_nothing(index_elements=["username"])` and omits `remember_token`.

- [ ] **Step 4: Reduce and retune Nginx login throttling**

Set:

```nginx
limit_req_zone $binary_remote_addr zone=login:1m rate=10r/m;
```

Keep the dedicated login location, change it to `limit_req zone=login burst=10 nodelay;`, retain status 429, and preserve the real-IP trust boundary.

- [ ] **Step 5: Run authentication tests**

Run from `backend`: `pytest tests/api/test_auth.py tests/test_create_admin.py tests/test_deployment_config.py -q`

Run from `frontend`: `npm test -- AuthProvider LoginPage`

Expected: PASS.

- [ ] **Step 6: Commit authentication simplification**

```bash
git add backend/app/core/security.py backend/app/api/routes/auth.py backend/app/schemas/auth.py backend/app/scripts/create_admin.py backend/tests/api/test_auth.py backend/tests/test_create_admin.py backend/tests/test_deployment_config.py frontend/src/auth/AuthProvider.tsx frontend/src/auth/AuthProvider.test.tsx frontend/src/pages/LoginPage.tsx frontend/src/pages/LoginPage.test.tsx frontend/nginx.conf
git commit -m "refactor: simplify stateless login"
```

---

### Task 6: Simplify the frontend to integer money and permanent current-state editing

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/lib/user-api.ts`
- Modify: `frontend/src/lib/user-api.test.ts`
- Modify: `frontend/src/components/LedgerForm.tsx`
- Modify: `frontend/src/components/LedgerForm.test.tsx`
- Modify: `frontend/src/pages/LedgerPage.tsx`
- Modify: `frontend/src/pages/LedgerPage.test.tsx`
- Rewrite: `frontend/src/components/RecordManagementDialogs.tsx`
- Modify: `frontend/src/components/RecordManagementDialogs.test.tsx`
- Modify: `frontend/src/pages/BusinessRecordsPage.tsx`
- Modify: `frontend/src/pages/BusinessRecordsPage.test.tsx`
- Modify: `frontend/src/admin/IncomeItemsPanel.tsx`
- Modify: `frontend/src/admin/IncomeItemsPanel.test.tsx`
- Modify reporting components and their tests that consume monetary API fields.

**Interfaces:**
- Produces: numeric money API types, `parseWholeAmount(value: string)`, `formatWholeEuro(value: number)`, no audit/config-version/row-version frontend state.
- Consumes: Tasks 3–5 API contracts.

- [ ] **Step 1: Write failing integer form and deletion-only tests**

Add unit tests proving:

- `parseWholeAmount("123")` returns `{ value: 123 }`.
- Empty, negative, decimal, exponent, and whitespace-wrapped values return a Chinese whole-number validation error.
- Only included categories contribute to the displayed total.
- A loaded old record uses its own `category_name`, `include_in_total`, and `sort_order`.
- Save sends no `config_version_id` or `expected_version`.
- Successful save resets dirty state before a date transition.
- Record management exposes permanent delete for an administrator but makes no `/history` or `/rollback` request.

- [ ] **Step 2: Run focused frontend tests**

Run from `frontend`: `npm test -- user-api LedgerForm LedgerPage RecordManagementDialogs BusinessRecordsPage IncomeItemsPanel`

Expected: FAIL because money helpers use cents, types expose history/version fields, and the UI still includes rollback and overwrite confirmation.

- [ ] **Step 3: Replace frontend money types and helpers**

Change ledger, record, database, chart, briefing, and composition money fields from decimal strings to numbers. Remove `AuditEntry`, config version fields, `row_version`, `income_config_version_id`, and `expected_version`.

Implement strict whole-number helpers:

```typescript
export function parseWholeAmount(value: string): { value: number } | { error: string } {
  if (!/^(0|[1-9]\d*)$/.test(value)) return { error: "金额必须是大于等于 0 的整数" };
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) return { error: "金额超出可保存范围" };
  return { value: parsed };
}

export function formatWholeEuro(value: number): string {
  const digits = new Intl.NumberFormat("de-DE", {
    maximumFractionDigits: 0,
    minimumFractionDigits: 0,
  }).format(value);
  return `€${digits}`;
}
```

- [ ] **Step 4: Simplify LedgerForm and LedgerPage**

Use `inputMode="numeric"`, `type="text"`, and strict integer parsing for money inputs. Sum only active included categories with normal safe integers. Preserve the existing saved-submission baseline mechanism so canonical server data clears dirty state.

Remove overwrite state/dialog, `overwrite=true`, version-conflict/config-version error branches, and version fields. A PUT always creates or overwrites. Keep the genuine unsaved-form transition guard and calendar marker queries.

- [ ] **Step 5: Remove history/rollback UI while preserving permanent delete**

Rewrite `RecordManagementDialogs` as an administrator-only permanent-delete confirmation. It receives `{storeId, record}` and calls `DELETE /api/ledger/{storeId}/{date}` without an expected-version query. On success invalidate ledger record, month markers, recent records, database results, charts, and dashboard keys. Non-admin users see record details but no destructive controls.

Remove history queries, pagination, rollback dialogs, `AuditEntry`, and history invalidation keys from Business Records and shared query helpers.

- [ ] **Step 6: Simplify current income configuration UI**

Remove version IDs and snapshot-key branches from `IncomeItemsPanel`. The saved response contains current categories and `enabled`. Retain add, reorder, include/exclude, archive, restore, and permanent-delete-unused behavior. Continue showing the formula preview and treating excluded items as recorded but not summed.

- [ ] **Step 7: Convert all monetary display and export helpers**

Update Home, Business Records, chart cards, record table/detail/mobile sheets, income composition, and browser export tests to display whole euros. Keep temperature/precipitation decimal formatting unchanged.

- [ ] **Step 8: Run the complete frontend test suite and production build**

Run from `frontend`: `npm test`

Then run from `frontend`: `npm run build`

Expected: both commands PASS with no TypeScript references to removed API fields.

- [ ] **Step 9: Commit the current-state frontend**

```bash
git add frontend/src frontend/tests
git commit -m "refactor: simplify integer ledger interface"
```

---

### Task 7: Add three-day online backups and seven-day operational retention

**Files:**
- Create: `backend/app/services/sqlite_backup.py`
- Create: `backend/app/services/operations_retention.py`
- Modify: `backend/app/services/scheduler.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/services/test_sqlite_backup.py`
- Create: `backend/tests/services/test_operations_retention.py`
- Modify: `backend/tests/services/test_scheduler.py`
- Modify: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `backup_sqlite(source: Path, destination: Path, today: date) -> Path`, `DailyScheduler`, `prune_operational_rows(session, now) -> OperationalRetentionResult`.
- Consumes: `Settings.database_path`, `backup_directory`, and `maintenance_timezone` from Task 1.

- [ ] **Step 1: Write failing backup tests**

Test all required cases with real SQLite files:

1. A source database backed up while another connection remains open produces a readable snapshot.
2. The final filename is `autolava-YYYYMMDD.sqlite3` and no `.tmp` remains.
3. `PRAGMA integrity_check` must return `ok` before promotion.
4. A simulated failed integrity check keeps the previous same-day backup.
5. Successful backup keeps today and the prior two calendar dates and removes the fourth.
6. Startup skips work when today's valid backup exists.

- [ ] **Step 2: Run backup tests and verify failure**

Run from `backend`: `pytest tests/services/test_sqlite_backup.py tests/services/test_operations_retention.py tests/services/test_scheduler.py -q`

Expected: FAIL because backup and daily scheduling services do not exist.

- [ ] **Step 3: Implement the synchronous SQLite online backup primitive**

Use Python's `sqlite3.Connection.backup()` inside a synchronous function invoked with `asyncio.to_thread`. Write to `autolava-YYYYMMDD.sqlite3.tmp`, run `PRAGMA integrity_check`, close both connections, and call `os.replace(temporary_path, final_path)` only after `ok`. Prune files by parsed filename date, never by broad recursive deletion or an unresolved path.

Use this implementation shape; tests may inject a failing integrity-check helper by monkeypatching `_integrity_result`:

```python
import os
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

_BACKUP_NAME = re.compile(r"^autolava-(\d{8})\.sqlite3$")


def _integrity_result(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    return "" if row is None else str(row[0])


def _prune_old_backups(destination: Path, today: date) -> None:
    cutoff = today - timedelta(days=2)
    for candidate in destination.glob("autolava-????????.sqlite3"):
        match = _BACKUP_NAME.fullmatch(candidate.name)
        if match is None:
            continue
        backup_date = date.fromisoformat(
            f"{match.group(1)[0:4]}-{match.group(1)[4:6]}-{match.group(1)[6:8]}"
        )
        if backup_date < cutoff:
            candidate.unlink()


def backup_sqlite(source: Path, destination: Path, today: date) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    final_path = destination / f"autolava-{today:%Y%m%d}.sqlite3"
    temporary_path = final_path.with_suffix(".sqlite3.tmp")
    temporary_path.unlink(missing_ok=True)
    try:
        with sqlite3.connect(source) as source_connection:
            with sqlite3.connect(temporary_path) as backup_connection:
                source_connection.backup(backup_connection)
        if _integrity_result(temporary_path) != "ok":
            raise RuntimeError("SQLite backup integrity check failed")
        os.replace(temporary_path, final_path)
        _prune_old_backups(destination, today)
        return final_path
    finally:
        temporary_path.unlink(missing_ok=True)
```

The implementation must return only after the final verified file exists; on error it removes only its exact temporary file and re-raises.

- [ ] **Step 4: Implement exact daily scheduling and startup catch-up**

Add a `DailyScheduler` that accepts a timezone, hour `3`, callback, clock, and sleeper for deterministic tests. On start, call the backup callback only when today's valid file is missing, then sleep until the next 03:00 in `ZoneInfo(settings.maintenance_timezone)`. Cancellation must stop promptly during FastAPI shutdown.

- [ ] **Step 5: Implement seven-day operational retention**

Delete `ScheduledTaskLog` rows where `created_at < now - timedelta(days=7)`. Delete only resolved `SystemAlert` rows where `resolved_at < cutoff`; never delete unresolved alerts based on age. Run retention after a successful or failed backup attempt in its own short database transaction.

The backup callback writes one `ScheduledTaskLog` with `task_type="sqlite_backup"`, UTC start/finish timestamps, and `status="success"` or `status="failed"`. Store only a bounded error summary; if SQLite itself is unavailable and the task log cannot be committed, emit the same summary through the Python logger.

- [ ] **Step 6: Wire lifecycle state and health behavior**

Create backup and operational-retention schedulers in `create_app()` only when `settings.environment.lower() == "production"`, expose them in `app.state`, start/stop them with existing weather scheduling, and ensure `/health` remains a cheap status response rather than running `integrity_check` on each request. Development startup must not create local automatic backups; backup unit tests invoke the service directly and lifecycle tests construct production settings explicitly.

- [ ] **Step 7: Run backup and lifecycle tests**

Run from `backend`: `pytest tests/services/test_sqlite_backup.py tests/services/test_operations_retention.py tests/services/test_scheduler.py tests/test_health.py -q`

Expected: PASS.

- [ ] **Step 8: Commit backup and retention**

```bash
git add backend/app/services/sqlite_backup.py backend/app/services/operations_retention.py backend/app/services/scheduler.py backend/app/main.py backend/tests/services/test_sqlite_backup.py backend/tests/services/test_operations_retention.py backend/tests/services/test_scheduler.py backend/tests/test_health.py
git commit -m "feat: add sqlite backup retention"
```

---

### Task 8: Replace MySQL runtime/deployment, simplify local launch, and delete Phase 2

**Files:**
- Modify: `compose.yaml`
- Delete: `compose.temporary.yaml`
- Modify: `.env.example`
- Modify: `backend/Dockerfile`
- Modify: `frontend/Dockerfile.prebuilt`
- Modify: `.github/workflows/ci.yml`
- Rewrite: `scripts/start-local.ps1`
- Delete: `scripts/backup-local-db.ps1`
- Delete: `scripts/restore-local-db.ps1`
- Delete: `scripts/backup-production-db.sh`
- Delete: `backend/app/scripts/inspect_runtime_database.py`
- Delete: `backend/tests/test_runtime_database_guard.py`
- Modify: `backend/tests/test_local_launcher.py`
- Modify: `backend/tests/test_deployment_config.py`
- Modify: `frontend/src/router.tsx`
- Delete: `docs/superpowers/plans/2026-07-13-autolava-ai-phase-2-workforce.md`
- Modify: `docs/superpowers/plans/2026-07-13-autolava-ai-roadmap.md`
- Modify: `docs/superpowers/plans/2026-07-13-autolava-ai-phase-3-agent.md`
- Modify: `docs/superpowers/plans/2026-07-13-autolava-ai-phase-4-automation-memory.md`
- Modify carefully: `README.md`
- Modify references: Phase 1/local-launcher plans and specs that currently promise a Phase 2 `/workers` route.

**Interfaces:**
- Produces: two-service Compose, `AUTOLAVA_DATABASE_PATH=/data/autolava.sqlite3`, persistent `/data`, prebuilt Web image, simple laptop launcher.
- Consumes: all runtime behavior from Tasks 1–7.

- [ ] **Step 1: Rewrite deployment and launcher contract tests first**

Make tests require:

- Compose services exactly `autolava-api` and `autolava-web`.
- API environment includes `AUTOLAVA_DATABASE_PATH=/data/autolava.sqlite3`, `AUTOLAVA_BACKUP_DIRECTORY=/data/backups`, and no database credentials.
- API mounts `autolava_data:/data`.
- No tracked runtime/config/dependency file contains `mysql`, `asyncmy`, `mysqldump`, `MYSQL_`, or `3306`.
- Web uses `Dockerfile.prebuilt` and server startup instructions use `--no-build`.
- CI defines no MySQL service and uses a temporary SQLite path.
- Local launcher contains migration/bootstrap/API/frontend commands but no MySQL connectivity, backup, restore, or production simulation.
- Router has no `/workers` path.

- [ ] **Step 2: Run deployment/launcher tests and verify failure**

Run from `backend`: `pytest tests/test_deployment_config.py tests/test_local_launcher.py -q`

Expected: FAIL with current MySQL Compose, CI, scripts, and worker placeholder.

- [ ] **Step 3: Build the two-service persistent Compose contract**

Update `compose.yaml` so API has one worker, `/data` volume, SQLite/backup paths, JWT/bootstrap settings, and an image tag that can be loaded on the server. Web must use the prebuilt Dockerfile. Keep the existing private network/real-IP boundary and exposed Web port. Do not define `mem_limit`, Redis, database, Agent, or placeholder services.

Delete `compose.temporary.yaml`. The server release command is `docker compose up -d --no-build` after loading locally/CI-built images.

- [ ] **Step 4: Simplify the laptop launcher**

Keep one PowerShell script that:

1. Checks `uv`, `node`, `npm`, ports 8000 and 5173.
2. Creates `.autolava-local`.
3. Installs dependencies when manifests change.
4. Collects bootstrap username/password and JWT secret when absent.
5. Sets `AUTOLAVA_DATABASE_PATH` to the local SQLite file.
6. Runs `alembic upgrade head` and `python -m app.scripts.create_admin`.
7. Starts one Uvicorn worker and Vite.
8. Stops only its owned child processes on exit.

Remove MySQL env-file merging, database host/port probes, database backup, and restore behavior. Keep the root ASCII-safe batch delegate.

- [ ] **Step 5: Convert CI and release-image checks**

Backend CI installs `aiosqlite`, runs a blank SQLite migration, Ruff, and full pytest without a service container. Container CI builds frontend `dist`, builds API plus prebuilt Web images, starts Compose, checks Nginx and proxied health, then removes the disposable CI volume. No server-side production build command is documented.

- [ ] **Step 6: Delete Phase 2 and document future boundaries**

Delete the Phase 2 plan and `/workers` placeholder. Update the roadmap to list Phase 1, Phase 3, and Phase 4 only. Remove `standard_work_hours` and Phase 2 promises from current docs. In Phase 3/4 plans, replace MySQL/workforce prerequisites with a prominent note that their details must be redesigned against SQLite, a 2-GB server, external APIs, measured remaining memory, and an optional future `compose.agent.yaml` overlay. Do not create that overlay or add implementation tasks for Agent or Phase 4 now.

- [ ] **Step 7: Update README without overwriting existing user edits**

First run `git diff -- README.md` and preserve unrelated content. Document:

- simple laptop startup;
- SQLite file locations;
- no old-data migration;
- prebuilt server image loading and `--no-build` startup;
- automatic three-day backups;
- no in-app restore;
- manual recovery warning: stop API before replacing the main file and remove stale `-wal`/`-shm` companions;
- empty database bootstrap;
- `docker stats` snapshots after idle and one normal workflow.

- [ ] **Step 8: Run deployment, launcher, and documentation checks**

Run from `backend`: `pytest tests/test_deployment_config.py tests/test_local_launcher.py -q`

Then run from the repository root: `rg -n "mysql|asyncmy|mysqldump|MYSQL_|3306|Phase 2|/workers|standard_work_hours" --glob '!docs/superpowers/specs/2026-07-18-sqlite-low-memory-runtime-design.md' --glob '!docs/superpowers/plans/2026-07-18-sqlite-runtime-simplification.md'`

Expected: tests PASS. The search returns no active runtime/product references; historical discussion references explicitly retained for provenance must be reviewed individually and cannot describe current behavior.

- [ ] **Step 9: Commit runtime and roadmap cleanup**

```bash
git add compose.yaml compose.temporary.yaml .env.example backend/Dockerfile frontend/Dockerfile.prebuilt .github/workflows/ci.yml scripts/start-local.ps1 scripts/backup-local-db.ps1 scripts/restore-local-db.ps1 scripts/backup-production-db.sh start-autolava.bat backend/app/scripts/inspect_runtime_database.py backend/tests/test_runtime_database_guard.py backend/tests/test_local_launcher.py backend/tests/test_deployment_config.py frontend/src/router.tsx docs/superpowers/plans/2026-07-13-autolava-ai-phase-2-workforce.md docs/superpowers/plans/2026-07-13-autolava-ai-roadmap.md docs/superpowers/plans/2026-07-13-autolava-ai-phase-3-agent.md docs/superpowers/plans/2026-07-13-autolava-ai-phase-4-automation-memory.md
git add -p README.md
git commit -m "refactor: deploy sqlite-only runtime"
```

Use the interactive README staging only to select the SQLite/deployment hunks created by this task; reject all pre-existing unrelated README hunks. Verify the staged README with `git diff --cached -- README.md` before committing.

---

### Task 9: Run complete verification, inspect compatibility, and prepare the release gate

**Files:**
- Modify only when a verification failure proves a missing requirement.
- Do not stage pre-existing unrelated working-tree changes without explicit user approval.

**Interfaces:**
- Consumes: complete implementation from Tasks 1–8.
- Produces: verified release candidate and an evidence-backed memory baseline procedure.

- [ ] **Step 1: Audit removed concepts across tracked source**

Run:

```powershell
rg -n "mysql|asyncmy|mysqldump|MYSQL_|with_for_update|dialects\.mysql|row_version|expected_version|remember_token|rollback|AuditLog|income_config_versions|standard_work_hours|/workers" backend frontend compose.yaml .env.example scripts .github README.md
```

Expected: no active implementation references. User-facing Chinese words such as “历史记录” may remain only when they mean real past business-day records, not audit history.

- [ ] **Step 2: Run backend quality gates**

Run from `backend`: `ruff check .`

Then run from `backend`: `pytest --cov=app --cov-report=term-missing`

Expected: both PASS. If the pre-existing untracked cleanup tests are discovered and fail because they import intentionally deleted models, do not delete or silently rewrite them; report the exact imports and ask whether the user wants those utilities updated and committed or kept outside the release.

- [ ] **Step 3: Run frontend quality gates**

Run from `frontend`: `npm test`

Then run from `frontend`: `npm run build`

Expected: PASS with no TypeScript error and no decimal-money snapshots.

- [ ] **Step 4: Run critical browser flows**

Run from `frontend`: `npx playwright test tests/daily-flow.spec.ts tests/admin-flow.spec.ts tests/responsive.spec.ts`

Expected: PASS for login, admin/store setup, current income configuration, multi-date integer ledger entry, blue dots, old-date autofill, overwrite save without false dirty warning, permanent delete, records/filtering/export, and responsive layout. No browser test may call history or rollback endpoints.

- [ ] **Step 5: Build and smoke-test release containers**

Build frontend `dist`, build/tag API and prebuilt Web images, run `docker compose config`, start the disposable stack, verify `/health`, login, SQLite persistence across container recreation, and a manual backup. Stop the disposable stack and remove only its explicitly named test volume.

Expected: only API and Web run; the database and verified backups persist across container recreation.

- [ ] **Step 6: Review implementation against every spec section**

Check the final diff against `docs/superpowers/specs/2026-07-18-sqlite-low-memory-runtime-design.md`, section by section. Explicitly record pass/fail evidence for integer money, snapshot behavior, no history/rollback/version/token state, three-day backup, Phase 2 deletion, optional future-service boundary, local launcher simplification, and production cutover.

- [ ] **Step 7: Request code review before merge/deployment**

Use `superpowers:requesting-code-review` on the complete branch. Fix confirmed correctness/security/data-loss issues, rerun the affected focused tests, then rerun the release gates in Steps 2–5.

- [ ] **Step 8: Commit verification-only fixes if needed**

```bash
git add -p
git diff --cached --check
git commit -m "fix: close sqlite release gaps"
```

Stage only hunks produced by verified release fixes, reject pre-existing user hunks, and do not create an empty commit when no fixes were necessary.

- [ ] **Step 9: Hand off production cutover and memory observation**

Before destructive production work, restate that MySQL data and volume will be permanently deleted. After the user authorizes the actual deployment turn, load prebuilt images, stop/remove old services and the exact MySQL volume, start SQLite API/Web, bootstrap admin, complete the production smoke test, then record:

```powershell
docker stats --no-stream
```

Capture one idle snapshot and one snapshot after a normal full workflow. Do not add a memory limit, 24-hour monitor, or synthetic peak script in this phase.
