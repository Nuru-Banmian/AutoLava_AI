# U13 Plan 03 Task 1 Report

## Outcome

- Added the structured `DashboardCardResponse` contract and persisted it in the nullable
  `daily_briefings.payload` JSON column while retaining `content` only as a compatibility fallback.
- Kept dashboard GET cache-only. It validates cached payloads and returns `state="unavailable"` for
  legacy rows whose payload is null without calling the weather provider.
- Made yesterday deterministic: only state and revenue are exposed, with no weather, categories,
  wash count, activity, AI text, or hint.
- Made today expose weather plus the ledger state/revenue, and tomorrow expose forecast state,
  weather, localized weekday, temperatures, and precipitation without ledger or revenue claims.
- Preserved ordered yesterday/today/tomorrow refreshes, atomic upserts, caller-owned transactions,
  the 04:00 scheduler, and yesterday-only regeneration after yesterday ledger changes.
- Localized the five-minute manual refresh response to `请等待五分钟后再刷新`.

## Necessary scope extension

The full-suite audit found two pre-existing integration assertions that still consumed the removed
API `content` field. `backend/tests/api/test_admin.py` and `backend/tests/api/test_ledger.py` were
updated to assert the equivalent structured state/revenue/weather fields. No production scope was
added beyond the brief.

## TDD evidence

- The original RED run produced 9 failures and 12 passes because structured payload persistence,
  response fields, cache fallback, and localized limiting did not exist.
- The focused briefing/dashboard/scheduler suite then passed 28 tests after the minimal structured
  implementation.
- A prior full run exposed exactly two obsolete `GET.content` assertions; each passed in isolation
  after its structured-contract update.
- On resume, the focused suite passed fresh at 28/28 before the final verification cycle.

## Verification

- Focused briefing/dashboard/scheduler: 28 passed.
- Full backend suite: 263 passed; one upstream Starlette/httpx deprecation warning.
- Alembic `0005` downgrade to `8b9c0d1e2f3a` and upgrade to
  `9c0d1e2f3a4b (head)`: passed against `autolava_test`.
- Ruff lint: all checks passed.
- Ruff formatting was applied only to U13-owned source/test additions; unrelated baseline
  formatting in the two migrated integration-test files was left untouched.
- `git diff --check`: passed.

All successful database commands loaded the ignored main-workspace test URL into their process,
verified its parsed database name was exactly `autolava_test`, and did not print credentials. Two
resume preflight attempts used the wrong relative environment-file location: the first was rejected
by the test database guard before any database fixture could run, and the second stopped before
pytest after parsing `autolava_local`. Neither is counted as product verification.

## Preserved workspace state and concerns

- Pre-existing `README.md`, progress, cleanup-script/test, and handoff changes were neither modified
  nor staged by U13.
- Untracked `backend/uv.lock` was absent from the U13 base and all repository history, had the
  standard generated uv lock format, and was created during the interrupted tool run. It was removed
  and is not included in this task.
- An additional `alembic check` reported two pre-existing metadata drifts for indexes created by
  migration `0004` (`ix_audit_domain_record_created` and `ix_daily_income_items_record_sort`). U13
  does not modify those models or indexes; the explicit `0005` downgrade/upgrade remains green.
- The backend suite retains one third-party Starlette/httpx deprecation warning; no U13 functional
  concern remains.

## Independent review

- Verdict: APPROVE WITH MINOR (0 Critical, 0 Important, 1 Minor); non-blocking for U14.
- The reviewer independently reran the focused suite at 28 passed and confirmed the structured
  fields, cache-only GET, null-payload fallback, hidden `content`, refresh behavior, Chinese limiter,
  and reversible migration comply with the brief.
- Minor test debt: the yesterday refresh-granularity test invokes the post-commit helper directly
  instead of exercising a public yesterday ledger mutation. A later regression test should prove
  through the ledger API that yesterday changes while the today/tomorrow payloads and timestamps
  remain unchanged.
