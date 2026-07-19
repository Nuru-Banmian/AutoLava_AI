# Ledger Current-State Commit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure ledger create, update, and delete operations commit against the latest authorization, store state, income mode, and active category snapshot after weather or SQLite lock waits.

**Architecture:** The route copies a `FrozenWeatherLocation`, ends the dependency-opened read transaction, and performs weather I/O without a database transaction. `LedgerService` then enters `sqlite_short_write`, reloads authorization and store state, and derives new-record income configuration inside the lock while preserving existing record snapshots.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async sessions, SQLite/aiosqlite, pytest-asyncio, HTTPX ASGI transport

## Global Constraints

- Weather provider execution must observe `session.in_transaction() is False`.
- Rejected writes return 401, 403, or 404 and leave ledger data unchanged.
- Existing records retain their saved `income_mode` and `DailyIncomeItem` snapshots.
- New records use the latest committed `Store.income_items_enabled` and active categories inside the SQLite write lock.

---

### Task 1: Current-State Ledger Interleaving Coverage

**Files:**
- Modify: `backend/tests/api/test_ledger_revocation.py`
- Verify: `backend/app/api/routes/ledger.py`
- Verify: `backend/app/services/ledger.py`

**Interfaces:**
- Consumes: `PausedWeather.entered`, `PausedWeather.release`, `LedgerService.upsert(...)`, and `sqlite_short_write(...)`.
- Produces: API-level proof that a new record uses the income mode and category snapshot committed while weather is paused.

- [x] **Step 1: Write the interleaving regression test**

Add a test that starts a composed-shaped PUT while the store is in legacy mode, waits for `PausedWeather.entered`, enables income items and changes the active category snapshot in an independent committed session, releases weather, and asserts a 201 response with a composed record using the new name, inclusion flag, and sort order.

- [x] **Step 2: Run the focused test against the existing implementation**

Run: `pytest tests/api/test_ledger_revocation.py -q`

Expected: all authorization and configuration interleavings pass because the lock-scoped current-state implementation is already present on this branch.

- [x] **Step 3: Confirm no production change is required**

Keep external weather I/O in `backend/app/api/routes/ledger.py` after `end_read_transaction(session)`. In `backend/app/services/ledger.py`, keep `require_fresh_store_access(...)`, `Store.income_items_enabled`, and the active `IncomeCategory` query inside `sqlite_short_write(...)`; do not change the existing-record branch that reads `record.income_mode` and `record.items`.

- [x] **Step 4: Run the ledger acceptance suite**

Run: `pytest tests/api/test_ledger.py tests/api/test_ledger_revocation.py tests/services/test_ledger.py tests/test_sqlite_database.py -q`

Expected: PASS, including transaction-boundary, 401/403/404 no-mutation, snapshot preservation, lock serialization, and configuration-switch coverage.

- [x] **Step 5: Run repository quality gates**

Run: `ruff check app tests`

Expected: PASS.

Run: `pytest -q`

Expected: PASS with no SQLite `ResourceWarning`.
