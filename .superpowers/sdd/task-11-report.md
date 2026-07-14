# Task 11 Release Packaging Report

## Scope

- Added a two-service Compose release (`autolava-api` and `autolava-web`) that connects to
  host-managed MySQL and contains no database container.
- Added production backend and multi-stage frontend images, Docker build-context exclusions,
  Nginx SPA hosting, and `/api/` plus `/health` reverse proxies.
- Added an asynchronous first-administrator command driven by
  `AUTOLAVA_BOOTSTRAP_USERNAME` and `AUTOLAVA_BOOTSTRAP_PASSWORD`. It hashes new passwords
  with `hash_password` and leaves any existing username completely unchanged.
- Added a GitHub Actions release gate with MySQL-backed migrations/backend tests and coverage,
  Ruff, locked frontend install/unit/build checks, explicit Playwright Chromium installation,
  browser tests, and Compose config/build jobs using non-sensitive CI-only placeholders.
- Expanded the README with host-MySQL deployment, secret setup, migration startup, and
  idempotent bootstrap instructions.

## TDD evidence

- Deployment RED: `python -m pytest tests/test_deployment_config.py -q` failed 4/4 with the
  expected `FileNotFoundError` results for the absent Compose, image, CI, and environment files.
- Bootstrap RED: `python -m pytest tests/test_create_admin.py -q` failed 3/3 solely because
  `app.scripts` did not exist.
- Focused GREEN: the combined deployment/bootstrap suite passed 7/7 against the dedicated
  MySQL test database.
- The admin tests prove password hashing, one-row repeat execution, changed-password rejection
  on the second execution, and preservation of an existing disabled worker's hash, role, and
  active state.

## Verification and diagnosed pre-existing test issue

- The first two full backend coverage runs each passed 157 tests and failed the existing
  concurrent briefing test. The failing test passed alone 3/3 but failed reliably after the
  preceding global-engine transaction test.
- Root cause was pooled async MySQL connections crossing pytest function-scoped event loops in
  the briefing module, whose direct global-engine tests bypassed the standard fixture cleanup.
  A test-only autouse fixture now disposes that engine after each briefing test; the reproducing
  two-test sequence passed 2/2 afterward. No briefing business code changed.
- `python -m pytest --cov=app --cov-report=term-missing`: 158 passed, 89% total coverage, with
  one existing Starlette `httpx` deprecation warning.
- `python -m ruff check .`: passed.
- `npm test`: 10 files and 58 tests passed.
- `npm run build`: passed, retaining the existing non-blocking large-chunk warning.
- `npx --no-install playwright test`: 3 tests passed using the existing Chromium installation.
- Deployment/static YAML contract tests: 4 passed as part of the backend suite.
- Docker Compose config/build were not run locally because no Docker executable is installed.
  Nothing was installed to work around that environment limitation; CI owns those gates.
- No dependency installation, external network call, push, or database-container addition was
  performed.

The final commit SHA is supplied in the handoff because a commit cannot contain its own object ID.
