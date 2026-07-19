# SQLite Final Issues 10–12 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the current-state safety coverage for income configuration and administration, then execute and record the SQLite branch release gates.

**Architecture:** All mutations enter `sqlite_short_write`, reload actor/capability and current target state inside the lock, then commit one short transaction. Category weather work remains between two non-nested write phases. Verification uses the public FastAPI HTTP boundary and persisted business outcomes, followed by a whole-branch review against the `main` merge base.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, SQLite/aiosqlite, HTTPX ASGI transport, pytest-asyncio, Ruff, openpyxl

## Global Constraints

- Execute Issue #10, then #11, then #12, with one independently reviewable commit per issue.
- Do not stage or modify pre-existing user changes in `AGENTS.md`, `.superpowers/sdd/progress.md`, `docs/agents/`, or `docs/superpowers/specs/2026-07-19-sqlite-final-review-repair-spec.md`.
- External weather work must run with `session.in_transaction() is False` and outside `SQLITE_WRITE_LOCK`.
- Rejected current-state mutations must leave target data unchanged.
- Do not restore MySQL, audit rollback, configuration versions, token state, or later Phase features.

---

### Task 1: Issue #10 — Income Configuration Current-State Safety

**Files:**
- Modify: `backend/tests/api/test_admin_revocation.py`
- Verify: `backend/app/api/routes/income_config.py`
- Verify: `backend/app/api/routes/admin.py`

**Interfaces:**
- Consumes: `PUT /api/admin/stores/{store_id}/income-config`, `SQLITE_WRITE_LOCK`, and the current authenticated actor.
- Produces: deterministic 401/no-mutation evidence when the actor is deactivated during the lock wait.

- [x] **Step 1: Add the API interleaving test**

```python
async def test_income_config_replace_rejects_actor_deactivated_after_lock_wait() -> None:
    await _reset_database()
    actor_id, target_id, store_id, category_id = await _setup_admin_mutation("replace")
    # Log in, hold SQLITE_WRITE_LOCK, start the PUT, deactivate actor in an
    # independent committed session, release the lock, and assert HTTP 401.
    # Reload Store and IncomeCategory and assert enabled/name remain unchanged.
```

- [x] **Step 2: Run the Issue #10 tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/api/test_income_config.py tests/api/test_admin_revocation.py -q`

Expected: PASS; if the new test fails, change only the affected route so `require_fresh_store_access(...)` remains inside `sqlite_short_write(...)`.

- [x] **Step 3: Commit Issue #10**

```powershell
git add -- backend/tests/api/test_admin_revocation.py docs/superpowers/plans/2026-07-19-sqlite-final-issues-10-12.md
git commit -m "test: verify income config current-state writes (#10)"
```

### Task 2: Issue #11 — Administration Current-State Safety

**Files:**
- Modify: `backend/tests/api/test_admin_revocation.py`
- Verify: `backend/app/api/routes/admin.py`

**Interfaces:**
- Consumes: user, store, and member mutation HTTP endpoints plus `SQLITE_WRITE_LOCK`.
- Produces: deterministic 401/403 and no-mutation evidence across user creation/deletion, store creation/update/deletion, and member replacement.

- [x] **Step 1: Extend setup and request helpers with administrative operations**

```python
operations = (
    "user-create",
    "user-delete",
    "store-create",
    "store-patch",
    "store-delete",
    "members-replace",
)
```

For every operation, start the public HTTP request while `SQLITE_WRITE_LOCK` is held, mutate the actor to inactive or role `user` in an independent committed session, then release the lock.

- [x] **Step 2: Assert current-state rejection and atomicity**

```python
assert response.status_code in {401, 403}
assert target_user_still_exists
assert original_store_payload_is_unchanged
assert original_member_ids_are_unchanged
assert no_requested_user_or_store_was_created
```

- [x] **Step 3: Run the Issue #11 tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/api/test_admin.py tests/api/test_admin_revocation.py -q`

Expected: PASS; any production fix must keep authorization and owner/last-admin checks inside the same `sqlite_short_write(...)` section as the mutation.

- [x] **Step 4: Commit Issue #11**

```powershell
git add -- backend/tests/api/test_admin_revocation.py
git commit -m "test: verify admin current-state mutations (#11)"
```

### Task 3: Issue #12 — Whole-Branch Release Gates and Review

**Files:**
- Create: `docs/superpowers/2026-07-19-sqlite-final-release-evidence.md`
- Modify only if a gate exposes a regression: the smallest affected source/test file.

**Interfaces:**
- Consumes: branch diff `git diff main...HEAD`, backend tests, Ruff, and source searches.
- Produces: reproducible release evidence and a two-axis code review of the complete SQLite branch.

- [x] **Step 1: Run static and backend gates**

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: Ruff PASS; all backend tests PASS; warnings contain no SQLite `ResourceWarning`.

- [x] **Step 2: Run historical export and prohibited-source checks**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_database.py -q
rg -n -i "mysql|audit|rollback endpoint|config(uration)? version|token state" backend/app
```

Expected: export tests PASS; source search finds no active implementations of removed subsystems (ordinary SQLAlchemy transaction rollback calls are not audit rollback).

- [x] **Step 3: Record exact evidence and deferred release conditions**

Create the evidence document with command, exit code, pass count, warnings, and explicit statements that Docker-enabled CI, production smoke testing, and memory snapshots remain later release conditions and were not claimed here.

- [x] **Step 4: Commit Issue #12 evidence**

```powershell
git add -- docs/superpowers/2026-07-19-sqlite-final-release-evidence.md
git commit -m "docs: record sqlite final release gates (#12)"
```

- [ ] **Step 5: Review the whole branch**

Resolve `main`, confirm `git diff main...HEAD` is non-empty, fetch Issues #7–#12 as the spec source, then run the `code-review` skill's Standards and Spec agents in parallel. Fix any confirmed blocking finding, rerun affected tests, and commit the fix before reporting completion.
