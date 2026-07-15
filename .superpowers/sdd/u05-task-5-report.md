# U05 Task 5 Report: Approved Login Page

## Status

DONE

Base: `67f16ea1fdf3e1f230e6912b0291de2d806a6786`

## Implemented

- Rebuilt the login page as the approved blue split layout with a brand panel and responsive single-column mobile presentation.
- Kept native username/password labels, `username` and `current-password` autocomplete, the remember-me input, full-width loading button, and the existing `login({ username, password, remember })` flow.
- Added a native keyboard-operable password visibility button with dynamic `显示密码` / `隐藏密码` accessible names; the password value is never logged or copied outside the submitted login payload.
- Routed login failures through `friendlyApiError(caught, "登录失败，请稍后重试")`, so disabled-account, credential, authorization, server, and network errors no longer expose English backend detail.
- Retained authenticated-user redirect to `/` and the loading guard that prevents the login form from flashing during session resolution.

## TDD evidence

1. Added the disabled-account regression test and observed the expected failure: the page rendered raw `Inactive user` instead of `这个账号已停用，请联系管理员`.
2. Added the password visibility/autocomplete regression test and observed the expected failure: `autocomplete="current-password"` was absent and no visibility control existed.
3. Implemented the minimal error mapping and accessible visibility state, then reran the focused suite successfully (2/2).

## Responsive and accessibility review

- Headless Chromium at 320×760 reported `innerWidth=320`, `documentElement.scrollWidth=320`, and `body.scrollWidth=320`; no horizontal overflow occurred.
- Browser inspection confirmed the password starts as `type="password"` with `autocomplete="current-password"`, then changes to `type="text"` after activating the visibility button.
- The visibility control is a native `type="button"` with a changing `aria-label`, so it is keyboard-operable and cannot accidentally submit the form.
- The 320px screenshot was visually reviewed: all fields, labels, brand copy, and the full-width login button fit without clipping, overlap, or green-theme remnants.

## Verification

- `npm test -- src/pages/LoginPage.test.tsx`: PASS, 2/2.
- `npm test -- src/pages/LoginPage.test.tsx src/auth/AuthProvider.test.tsx`: PASS, 15/15.
- `npm test`: PASS, 12 files and 93/93 tests.
- `npm run build`: PASS (`tsc -b && vite build`). Vite reports only the existing large-chunk advisory.
- `git diff --check`: PASS.
- Self-review confirmed the login payload, loading state, authenticated redirect, and mobile navigation code were not changed.
- Preserved unrelated dirty files: `README.md`, `.superpowers/sdd/progress.md`, both cleanup scripts, and both cleanup tests.
