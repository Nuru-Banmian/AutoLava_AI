# U09 Task 2 Report: Direct-Total and Composed Form Modes

## Status

DONE

## Scope delivered

- Added `incomeConfigKey(storeId)` and loaded the current store configuration from `GET /api/income-config/{store_id}/current` in `LedgerPage`.
- Added mutually exclusive ledger form modes:
  - disabled configuration: one `当日营业额` input, canonical `daily_revenue`, `items: []`, and no configuration version;
  - enabled configuration: active configured income inputs only, computed display total, `daily_revenue: null`, and the bound configuration version.
- Kept `config_version_id` and `expected_version` out of the visible UI while preserving the required optimistic-concurrency payload.
- Preserved total-only records as total-only when the current store configuration is composed.
- Bound historical composed edits to their record snapshot items, so a newer current configuration cannot add fabricated categories or discard historical ones.
- Kept the existing Chinese amount validation and `洗车数量` copy. No calendar or compact-layout work was introduced.
- Filled a plan integration gap by adding the real read-only current-configuration endpoint. The original brief consumed this endpoint, but the baseline only exposed administrator configuration endpoints.

## Backend integration-gap repair

- Added only `GET /api/income-config/{store_id}/current`.
- Reused `require_store_access`, `IncomeConfigService.current`, and `IncomeConfigService.response`.
- Assigned regular users and administrators can read current configuration.
- Unassigned, inactive, and missing stores retain the existing non-disclosure `404 Store not found` semantics.
- Administrator version-history and mutation routes remain protected by the administrator dependency; regular users still receive `403`.
- No regular-user history, publish, restore, archive, or delete capability was added.

## TDD evidence

1. Direct-total RED: `LedgerForm.test.tsx` failed because `当日营业额` did not exist. Minimal mode rendering/submission turned it green.
2. Configured-items and legacy-total RED: tests failed because catalog-only/disabled items were rendered and an existing total-only record was converted to composed mode. Configuration-backed fields plus record-shape mode selection turned them green.
3. Page-query RED: `incomeConfigKey` was absent and `LedgerPage` did not load or pass current configuration. The query key/request/loading/error integration turned the page suite green.
4. Backend endpoint RED on guarded `autolava_test`: three new tests failed with route-level 404 while five existing income-config tests passed. The read-only route and router registration turned all eight green.
5. Historical-composed RED: a category added to the current configuration appeared in an older composed record. Binding edit fields to `record.items` turned the focused form suite green.

## Verification

- Related backend income-config and ledger API/service tests: `52 passed`.
- Backend full suite: `251 passed`, with one existing Starlette/httpx deprecation warning.
- Ruff: `All checks passed!`.
- Frontend full suite: `15 files, 109 tests passed`.
- Focused frontend suite: `LedgerForm.test.tsx` and `LedgerPage.test.tsx`, `14 tests passed`.
- Production build: passed; Vite emitted only its existing large-chunk advisory.
- `git diff --check`: passed.

Backend tests loaded the ignored worktree database setting into the test process and redirected only the database name from `autolava_local` to the dedicated disposable `autolava_test`; credentials were not printed.

## Self-review

- New records follow the current configuration flag; existing records follow their persisted income shape.
- Direct mode never submits category items or a configuration version.
- Composed mode never submits a client-computed daily total.
- Current active configuration items are the only inputs for new composed records.
- Existing composed edits submit exactly their snapshot categories and preserve their snapshot version/row version.
- The form remains reusable from the existing database edit entry through a record-derived compatibility configuration when no explicit current configuration is supplied.
- Existing unrelated dirty files (`README.md`, `.superpowers/sdd/progress.md`, cleanup scripts/tests) were neither edited by U09 nor included in the planned commit.

## Independent-review remediation

The first U09 commit was not review-clean because it inferred an existing record's mode from a non-null `income_config_version_id`. Backend records created under a disabled configuration still retain that configuration id, while their authoritative mode is `income_mode: "legacy_total"`.

The follow-up fixes are:

- Added the exact `income_mode: "legacy_total" | "composed"` field to `RecordSnapshot` and made it the sole mode discriminator for existing records.
- Added `category_name`, `include_in_total`, and `sort_order` to `RecordItem`; historical composed rendering now uses those typed snapshot fields with no unsafe cast.
- Added `created_at: string | null` to `IncomeConfigResponse` and updated current-config fixtures to match the real response schema.
- Added a backend create → fetch → overwrite regression proving a disabled configuration produces a `legacy_total` record with a non-null configuration version and remains editable with direct revenue.
- Added LedgerForm and DatabasePage regressions proving that production shape displays and submits `daily_revenue` with empty `items`.
- Added a dedicated current-config error branch using `friendlyApiError`; an English 500 detail is not exposed, and “重试收入配置” refetches only the failed config query. Already-successful catalog and record dependencies are not redundantly fetched.

### Review-fix TDD evidence

1. Authoritative-mode RED: LedgerForm and DatabasePage tests both failed because the non-null config version reopened a `legacy_total` record as an empty composed form. Switching existing-record mode selection to `record.income_mode` turned both green.
2. Config-error RED: LedgerPage rendered `Internal Server Error` directly and had no retry action. A friendly Chinese error plus config-only refetch turned the test green.

### Final review-fix verification

- Backend ledger API focused suite: `28 passed`.
- Backend full suite: `252 passed`, with one existing Starlette/httpx deprecation warning.
- Ruff: `All checks passed!`.
- Frontend focused suite (`LedgerForm`, `LedgerPage`, `DatabasePage`): `3 files, 25 tests passed`.
- Frontend full suite: `15 files, 111 tests passed`.
- Production build: passed; Vite emitted only its existing large-chunk advisory.
- `git diff --check`: passed.
