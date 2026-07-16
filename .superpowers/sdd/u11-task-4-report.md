# U11 Plan 02 Task 4 Report

## Outcome

- Reordered the ledger into a compact status → income → computed total flow.
- Kept income visible by default and added accessible collapsed `天气` and `洗车数量 / 活动` sections whose values survive collapse/expand.
- Added state-aware submit labels: `保存今日记录`, `保存修改`, and `补记历史记录`.
- Recovered configuration-version 409 responses with a Chinese message, exact current-config and current-record invalidation, and preserved unsaved form input.
- Added one shared unsaved-change guard for date changes, store changes, React Router navigation, and browser `beforeunload`; clean and successfully saved forms do not prompt.
- Converted ledger-facing backend errors to friendly Chinese messages.
- Added a 320 px Playwright ledger check for accessible collapse controls, preserved values, and no page-level horizontal scrolling.

## Necessary scope extension

The original brief named the form/page files. The parent authorized the minimum additional scope needed to prevent store and route changes from bypassing the ledger guard:

- `frontend/src/navigation/UnsavedChanges.tsx`
- `frontend/src/navigation/UnsavedChanges.test.tsx`
- `frontend/src/stores/StoreProvider.tsx`
- `frontend/src/layouts/AppShell.tsx`
- `frontend/tests/responsive.spec.ts`

No Task 5 delete or permission behavior was added.

## TDD evidence

Each behavior was observed failing before its minimal implementation:

1. Missing collapsed controls and submit label.
2. Configuration 409 incorrectly opened overwrite confirmation and did not refetch dependencies.
3. Form did not report dirty state from its loaded snapshot.
4. Dirty date changes navigated silently.
5. Dirty store changes bypassed confirmation.
6. Dirty React Router navigation proceeded immediately.
7. `beforeunload` did not activate only while dirty.
8. Successful save left the guard active.

## Verification

- Focused frontend: `25 passed`.
- Full frontend Vitest: `17 files, 129 passed`.
- Frontend build: passed (`tsc -b && vite build`); Vite emitted the existing large-chunk advisory only.
- Playwright responsive file: `5 passed`.
- Full Playwright suite: `5 passed`.
- Backend ledger and income-config regression: `53 passed` against the dedicated `autolava_test` database.
- `git diff --check`: passed.

The first backend attempt was intentionally rejected by the test fixture because no dedicated `autolava_test` URL was configured. It executed zero tests. The command was rerun with a process-only URL derived for `autolava_test`, producing the passing result above.

## Preserved workspace state

Pre-existing changes to `.superpowers/sdd/progress.md`, `README.md`, and the untracked cleanup scripts/tests were not modified or staged by this task.

## Review repair

### Outcome

- Changed configuration-version mismatches to HTTP 409 while preserving ordinary request validation as 422 and row-version conflicts as 409.
- Routed same-user asynchronous store reconciliation through the shared unsaved-change guard, retained the revoked-store snapshot until confirmation, and cleared prior-account state immediately on account changes.
- Added a canonical semantic form baseline and exact saved-submission revision. Amount spellings such as `12,3`/`12.30`, trimmed activity text, and submitted numeric values compare by payload meaning rather than display spelling.
- Canonical refetches no longer re-arm dirty state; edits made after a save starts remain dirty and are not overwritten; a conflict refetch that changes 404 into an existing record does not replace dirty input. Clean forms still absorb server and late automatic-weather snapshots.
- Made StoreProvider test teardown deterministic by unmounting providers before clearing local storage.

### TDD evidence

The unfinished LedgerPage tests were run before implementation and failed in exactly three expected ways:

1. Configuration-conflict refetch replaced entered `123.45` with server `999.00`.
2. A canonical existing-record save left `beforeunload` blocked.
3. A newer `20` edit made during a pending save was replaced by refetched `10.00`.

After the semantic-baseline implementation, the focused LedgerPage/LedgerForm suite passed 25/25. A final diff audit found that late automatic weather was not part of the incoming clean snapshot; a new focused test failed with an empty weather input, then passed after adding automatic weather to the incoming signature. The final focused count was 26/26.

The StoreProvider file exposed a teardown-order flake twice under broader execution. The failing next test inherited `Roma` because local storage was cleared before the preceding provider was unmounted. After explicit cleanup-before-clear, the file passed three consecutive runs at 8/8 and the full frontend suite passed.

### Verification commands and results

- `npm test -- --run src/navigation/UnsavedChanges.test.tsx src/stores/StoreProvider.test.tsx src/pages/LedgerPage.test.tsx src/components/LedgerForm.test.tsx` — 4 files, 35 passed.
- `npm test -- --run src/components/LedgerForm.test.tsx src/pages/LedgerPage.test.tsx` — 2 files, 26 passed after the final weather regression.
- `npm test -- --run` — 17 files, 134 passed.
- `npm run build` — passed (`tsc -b && vite build`).
- `npm run test:e2e` — 5 passed, including the 320 px compact-ledger check.
- `uv run pytest tests/api/test_ledger.py -q` with the process-only `autolava_test` URL — 29 passed.
- `uv run pytest -q` with the process-only `autolava_test` URL — 253 passed.
- `uv run ruff check .` — all checks passed.
- `git diff --check` — passed.

### Commit and concerns

- Commit: `fix: recover conflict-safe ledger state` (this report is included in that repair commit; the resulting hash is returned in the task handoff).
- The frontend build retains the existing large-chunk advisory.
- The backend full suite retains one upstream Starlette/httpx deprecation warning.
- The first backend attempts executed zero tests because the database environment was loaded from the wrong working directory; the successful commands above ran from `backend` and injected only the dedicated test database URL without printing it.

## Resume re-review repair — 2026-07-16

### RED evidence

All three re-review findings were reproduced before production changes:

1. A second `requestTransition` replaced the active transition; its cancel callback was called zero times.
2. With revoked-store reconciliation pending first and a route blocker second, discard executed the route action instead of the store fallback.
3. After a saved creation refetched a realistic three-item canonical record with automatic weather `晴`, the UI absorbed the weather but `beforeunload` remained blocked.
4. Cancelling a revoked-store reconciliation and then becoming clean/refetching the same list left the revoked Berlin snapshot selected instead of applying Roma.

The first route/store test did not force the competing effect to run and passed incorrectly. It was corrected to make store reconciliation the confirmed active transition before requesting the route, then failed with the wrong route action as expected.

### GREEN implementation

- `UnsavedChangesProvider` now owns one synchronous active transition. A competing request is rejected through its own cancel callback, so route blockers reset instead of being silently displaced.
- Store reconciliation clears only its matching reconciliation key when cancelled or rejected. Dirty-to-clean changes or a same-list refetch can therefore reconsider the fallback without repeated dialogs while the original request remains active.
- A saved submission is now only a temporary semantic baseline until the record query revision changes. Clean canonical absorption consumes that exact revision and promotes the server snapshot; dirty drafts leave the revision pending and are not overwritten.
- Removed the redundant saved-submission baseline effect that could run after canonical absorption in the same render and restore the pre-canonical signature.

### Verification commands and results

- Four focused files — `40 passed`; repeated three consecutive times at `40/40`.
- `npm test -- --run` — 17 files, 138 passed.
- `npm run build` — passed; existing large-chunk advisory only.
- `npm run test:e2e` — 5 passed.
- `uv run pytest tests/api/test_ledger.py -q` with the process-only `autolava_test` URL — 29 passed.
- `uv run pytest -q` with the process-only `autolava_test` URL — 253 passed; existing Starlette/httpx deprecation warning only.
- `uv run ruff check .` — all checks passed.
- `git diff --check` — passed.

### Commit and concerns

- Commit: `fix: serialize unsaved ledger transitions` (this report is included in the commit; the resulting hash is returned in the task handoff).
- No backend production files changed in this follow-up; backend tests were rerun to verify the existing 409 contract.
