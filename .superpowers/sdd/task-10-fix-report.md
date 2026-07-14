# Task 10 Independent Review Fix Report

## Revision and constraints

- Reviewed implementation SHA: `92bcc5f7532544264e074dc2014cc98b0ee25bcb`
- Fix commit message: `fix: bind user actions to store scope`
- No push, dependency installation, browser installation, backend change, or database access was performed.

## Confirmed review findings and fixes

- Ledger mutations now carry immutable `{storeId, date, body}` variables through first save, 409 confirmation, overwrite, and invalidation. Stale 409/success/error results cannot affect a newly selected scope; pending confirmation clears on store/date change.
- Database edit/delete/rollback state and mutation variables carry the originating store and record/audit identity. Completion invalidates the captured store, stale errors do not leak into the new store, and action dialogs clear on store changes.
- User-data invalidation now matches each query family's documented store-id position. A regression proves store `7` no longer invalidates store `1`'s `recent(..., days=7)` query.
- Ledger decimal input is canonicalized to dot-separated two-decimal strings. Empty, negative, malformed, over-scale, and values above `NUMERIC(12,2)` maximum `9999999999.99` are blocked with a visible error rather than silently counted as zero.
- Charts category catalog is scoped to the selected start/end range, renders the complete returned catalog including inactive historical categories, deterministically reconciles selection, and cannot issue chart queries with stale range/store selections.
- Charts catalog, Ledger recent records, and Database history now have distinct loading, error, and retry UI; errors are no longer presented as empty results.
- Financial text formatting no longer uses JavaScript `Number`. Chart data retains raw decimal strings for tooltips and uses an explicitly bounded numeric projection only for Recharts geometry.
- Home refresh errors reset and are scope-filtered on store changes.
- Database next-page availability is calculated from `total` rather than current item count.
- Quick-range tests freeze `Date`, removing wall-clock dependence.

## TDD evidence

Observed RED failures before implementation included:

- wrong-store query invalidation caused by `queryKey.includes(storeId)`;
- missing canonical decimal, exact money, and safe chart projection helpers;
- comma amount submitted unchanged and invalid amount silently totaled as zero;
- Ledger overwrite/invalidation moving to the newly selected store;
- Home refresh error persisting after store change;
- recent/history/catalog errors rendered as empty state with no retry;
- catalog fixed to today, inactive categories hidden, and stale range selection;
- Database and chart large decimal text losing precision;
- chart tooltip missing the raw decimal value.

Focused GREEN command:

- `npm test -- LedgerPage HomePage DatabasePage ChartsPage user-api ChartPanel`
- Result: exit 0; 6 files and 30 tests passed.

## Verification

Commands run from `frontend` unless stated otherwise:

- `npm test` — exit 0; 10 files and 57 tests passed.
- `$env:PLAYWRIGHT_HTML_OPEN='never'; npx --no-install playwright test tests/responsive.spec.ts` — exit 0; 3 tests passed using the existing browser.
- `npm run build` — exit 0; TypeScript and Vite production build passed, retaining the existing non-blocking large-chunk warning.
- `git diff --check` — exit 0.

The final commit SHA is recorded in the completion handoff because a Git commit cannot embed its own final object SHA.

## Re-review pagination fix

- Re-reviewed implementation SHA: `d1b9b635ebbe8b3a63accc7408b00024914a9da7`.
- Confirmed the database endpoint derives category descriptors from the paginated record query, so a single `page=1&page_size=200` request could omit inactive categories used only by later records.
- The chart catalog loader now captures the selected store and date range, requests every 200-record page, forwards the query abort signal, merges descriptors by category ID, and completes before selection reconciliation or chart querying is enabled.
- The database test suite restores real timers in `afterEach`, even when the quick-range test fails before its final assertion.
- TDD RED: `npm test -- ChartsPage.test.tsx --run` failed 1 of 8 tests because the page-2 inactive category was absent.
- Focused GREEN: `npm test -- ChartsPage.test.tsx DatabasePage.test.tsx user-api.test.ts --run` passed 3 files and 19 tests.
- Final verification: `npm test` passed 10 files and 58 tests; responsive Playwright passed 3 tests; `npm run build` passed with the existing non-blocking large-chunk warning; `git diff --check` passed.
