# U10 Plan02 Task3 Report — Shared Store-Timezone Calendar

## Outcome

- Added reusable `MonthCalendar({ month, selected, today, recordedDates, onSelect })` and `LedgerDatePicker({ value, today, recordedDates, onChange })` components.
- Replaced the ledger page's browser-local native date input with a visible store-date trigger.
- Desktop uses a right-aligned dialog popover; narrow screens use a bottom sheet.
- Added today/yesterday shortcuts, Monday-first weeks, cross-month cells, recorded-date dots, selected state, and future-date disabling.
- Recorded dates combine the recent-record query with the selected record query, so both recent entries and an existing selected historical entry show “编辑已有记录”; missing dates show “补记历史记录”.
- Kept date-only comparisons based on the store-local `today` string. No browser-local “today” calculation was added.

## TDD Evidence

1. RED: `MonthCalendar` import missing for recorded dot / selected / future-disabled contract.
2. GREEN: implemented date-fns interval generation and native date buttons.
3. RED: cross-month cells lacked an explicit outside-month marker.
4. GREEN: added `data-outside` while preserving Monday-first boundaries.
5. RED: `LedgerDatePicker` import missing for trigger, shortcuts, and month navigation.
6. GREEN: added controlled Dialog/Sheet picker. A focused run then exposed swallowed Radix `asChild` events; root cause was isolated and the controlled trigger fixed minimally.
7. RED: LedgerPage still exposed only the old native input.
8. GREEN: integrated shared picker and recorded-date query data. The first integration run exposed an empty-date async initialization frame; root cause was traced to store selection arriving before the date effect, and the trigger now safely uses `date || today`.

## Coverage

- Recorded dot, selected state, callback, and future disabling.
- Monday-first header and July 2026 boundaries (`2026-06-29` through `2026-08-02`).
- Desktop dialog flow, today/yesterday shortcuts, previous/next month navigation.
- Narrow-screen bottom-sheet branch.
- Ledger query rescoping after calendar selection and existing overwrite/invalidation concurrency behavior.
- Store timezone edges: Honolulu previous UTC day, Kiritimati UTC+14 year boundary, and both sides of the New York 2026 DST transition.
- ARIA grid structure with native buttons, dialog naming, keyboard-focusable controls, and blue theme tokens.

## Verification

- Focused: `npm test -- src/components/MonthCalendar.test.tsx src/pages/LedgerPage.test.tsx` — 21/21 passed after review remediation.
- Full frontend: `npm test` — 121/121 passed after review remediation.
- Build: `npm run build` — passed (`tsc -b` and Vite); existing bundle-size warning remains.
- Browser: `npm run test:e2e` — 4/4 responsive Playwright tests passed, including the existing 320px document-width assertions.
- `git diff --check` — passed.

## Scope / Worktree Safety

- No compact ledger form or full history-page work was added.
- Existing dirty README, progress, cleanup scripts, and backend cleanup tests were preserved and excluded from this task's staging scope.

## Review Remediation

- Froze `Date` for every `LedgerPage` test with `vi.useFakeTimers({ toFake: ["Date"] })`, set the baseline instant explicitly, and restored real timers after every test. Calendar/picker component tests continue to receive `today` directly as their injected clock.
- Added a rendered-page boundary case at `2031-01-01T01:30:00Z` proving Honolulu's store-local date is `2030-12-31` and January 1 is disabled, so the suite is structurally independent of the wall-clock date.
- RED confirmed the grid had no owned rows, no roving tab stop, and no arrow navigation. GREEN now renders a header row plus week rows, exposes selected grid cells, maintains exactly one enabled date at `tabIndex=0`, and synchronizes the roving stop whenever a date receives focus.
- Added real `userEvent` coverage for Arrow Left/Right/Up/Down, Home/End, a visible cross-month boundary, future-date focus blocking, and Enter/Space selection.
- RED confirmed the plain picker button lacked `aria-haspopup`. `DateTrigger` now forwards its ref and injected props through Radix `DialogTrigger`/`SheetTrigger`, providing dynamic `aria-expanded`/`aria-controls` semantics on both layouts and restoring focus after Escape or selection.
