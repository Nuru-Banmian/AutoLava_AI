# U08 Task 1 Report: Lock Ledger API Contract

## Status

DONE

## Scope delivered

- Added a backend regression covering a composed ledger write bound to the published configuration version and asserting the recomputed daily revenue.
- Added the exact `IncomeConfigResponse`, `IncomeConfigItem`, and expanded `LedgerBody` TypeScript contracts from the task brief.
- Completed the existing record snapshot contract with `income_config_version_id` and `row_version`, which are already returned by the backend.
- Bound edited composed-record submissions to `config_version_id`, `expected_version`, and `daily_revenue: null`.
- Added the dedicated `LedgerForm.test.tsx` contract regression.
- Did not implement Task 2 configuration loading, direct-total UI, or any later UI work.

## TDD evidence

- Backend contract baseline: 26 passed.
- Backend regression after addition: 27 passed. This test was expected to pass immediately because the backend contract already supported the fields, as stated in the plan.
- Frontend RED: the new form test failed because the submitted body omitted `config_version_id`, `expected_version`, and `daily_revenue`.
- Frontend GREEN: the same focused test passed after the minimal type and payload changes.

## Verification

- `backend/.venv/Scripts/pytest.exe tests/api/test_ledger.py -q -p no:cacheprovider`: 27 passed.
- `backend/.venv/Scripts/pytest.exe tests -q -p no:cacheprovider`: 248 passed, with one existing Starlette/httpx deprecation warning.
- `backend/.venv/Scripts/ruff.exe check app tests`: all checks passed.
- `npm test -- src/components/LedgerForm.test.tsx src/pages/LedgerPage.test.tsx`: 10 passed.
- `npm run build`: passed; Vite reported only its existing large-chunk advisory.
- `git diff --check`: passed.

The backend test database URL was loaded from the worktree `.autolava-db.env`; only `autolava_local` was replaced with `autolava_test` in the test process.

## Self-review

- Existing-record writes use the backend snapshot version fields; new-record writes remain `null` until Task 2 supplies the current income configuration.
- The composed total continues to be recomputed by the backend; the frontend sends `daily_revenue: null`.
- No user-facing configuration-version fields were added.
- Pre-existing dirty files were not modified or staged.
