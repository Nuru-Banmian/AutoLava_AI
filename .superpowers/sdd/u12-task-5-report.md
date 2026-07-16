# U12 Plan 02 Task 5 Report

## Outcome

- Preserved the backend capability contract: ordinary users retain `ledger.create` and
  `ledger.edit`, but have neither `ledger.delete` nor `audit.view`.
- Added API regression coverage proving an assigned ordinary user receives HTTP 403 from both the
  ledger delete endpoint and the audit rollback endpoint.
- Made `DatabasePage` use the authenticated role as a presentation gate. Ordinary users keep the
  edit action, do not request or render audit history, and cannot see delete or rollback controls.
- Preserved the existing admin delete, history, rollback, and confirmation flows.

## Necessary scope extension

The brief listed `DatabasePage.tsx`, but the delete button is owned by the shared `RecordTable`.
`frontend/src/components/RecordTable.tsx` therefore received the minimum interface change needed:
`onDelete` is optional and the delete button is rendered only when the callback is supplied.

## TDD evidence

- Backend permission tests passed immediately after being added because the existing route
  dependencies and role capabilities already enforce the required authority boundary.
- The new ordinary-user frontend test failed before production changes because it found
  `删除 2026-07-13`.
- After the minimal role gate and optional delete callback, the focused DatabasePage suite passed
  11/11. The test also proves edit remains visible, audit history is not requested, and history and
  rollback UI are absent.

## Verification

- Backend ledger/database/access focus: 54 passed.
- Frontend LedgerPage/DatabasePage focus: 2 files, 35 passed.
- Backend full suite: 255 passed; one existing Starlette/httpx deprecation warning.
- Ruff: all checks passed.
- Frontend full Vitest: 17 files, 141 passed.
- Frontend build: passed; existing Vite large-chunk advisory only.
- Playwright E2E: 5 passed, including the 320 px database scrolling and exact mobile navigation
  checks.
- `git diff --check`: passed.

The backend commands loaded `.autolava-db.env` only into the test process and replaced
`autolava_local` with `autolava_test`; credentials were not printed.

## Preserved workspace state and concerns

- Pre-existing `README.md`, progress, cleanup-script/test, and handoff changes were not modified or
  staged by this task.
- No capability conflict was found. The backend was already authoritative; the frontend change is
  defense-in-depth and avoids a known 403 request for ordinary users.
- The shared table's optional callback is the only file change beyond the brief's original source
  list.
