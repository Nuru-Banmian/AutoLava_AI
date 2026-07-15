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
