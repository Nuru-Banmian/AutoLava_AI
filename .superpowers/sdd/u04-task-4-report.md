# U04 Task 4 Report: Role-Aware Shell and Mobile More Page

## Status

DONE

Base: `3351e3bd6c5bbabf1668fcd75cb422efd023eccf`

## Implemented

- Added centralized `navigationFor(role, surface)` metadata.
- Rebuilt the application shell with a fixed approved-blue desktop sidebar and a four-entry mobile bottom bar.
- Desktop order is exactly 首页、每日记账、历史记录、经营分析、管理中心（admin only）.
- Mobile order is exactly 首页、记账、记录、更多 for both roles.
- Added `/more` with 经营分析、门店切换、修改密码、退出登录; administrators additionally see 管理中心 and 系统状态.
- Registered `/more` and `/account/password`; retained the authoritative backend admin capability checks and the frontend admin route guard.
- Replaced shell/auth/network error detail leakage with Chinese user-facing messages.
- Preserved `pb-24 md:pb-6`; the mobile bar uses `grid-cols-4`, `min-w-0`, compact padding, and truncated labels.

## TDD evidence

1. Added the regular-user `/more` navigation test. It failed because `/more` was not registered, then passed after the minimal shell/navigation/page implementation.
2. Removed the untested administrator More links, added the administrator branch test, observed failure for missing 管理中心, then restored the minimal role branch and passed.
3. Removed the untested desktop admin module, added the exact-order test, observed the missing 管理中心 failure, then restored the role-aware module and passed.
4. Added an auth-load failure test with an English server error, observed the English text failure, then implemented the Chinese message and passed.

## Brief file-list exception

`frontend/src/auth/AuthProvider.test.tsx` required a minimal update even though it was omitted from the brief file list. The pre-U04 test required the removed visible Phase 2 员工管理 item, old 管理 label, and old top-nav structure, directly conflicting with the approved U04 fixed navigation contracts. Full-suite evidence was 88/89 with that stale assertion. The test now asserts the exact five desktop links, exact four mobile links, administrator visibility, regular-user invisibility, and the approved Chinese logout/store error messages. No unrelated test behavior was changed. This exception was explicitly approved by the parent coordinator.

## 320px responsive review

- Four equal grid columns yield 80px per mobile item at 320px; link nodes use `min-w-0`, 4px horizontal padding, and truncated labels, so items cannot overlap.
- The shell has no fixed/minimum content width; mobile main content is 288px after 16px side padding.
- The More-page store row fits within its 256px inner card width, and the bottom bar is compensated by 96px main-content padding.
- Existing Playwright responsive tests were attempted once but produced no output for about 70 seconds and were terminated per coordinator instruction. They were not repeated. Structural DOM regression assertions cover the four-column/four-link contract.

## Verification

- `npm test -- src/App.test.tsx`: PASS, 8/8.
- `npm test`: PASS, 11 files and 90/90 tests.
- `npm run build`: PASS (`tsc -b && vite build`). Vite reports only the pre-existing large-chunk advisory.
- `git diff --check`: PASS.
- Backend authorization inspection confirms admin APIs still depend on `require_capability(...)`; this task made no backend authorization changes.
- Preserved unrelated dirty files: `README.md`, `.superpowers/sdd/progress.md`, both cleanup scripts, and both cleanup tests.
