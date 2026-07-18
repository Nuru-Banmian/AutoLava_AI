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

## Verification and diagnosed briefing concurrency issue

- The first two full backend coverage runs each passed 157 tests and failed the existing
  concurrent briefing test. The failing test passed alone 3/3 but failed reliably after the
  preceding global-engine transaction test.
- The initial pooled-connection/event-loop diagnosis was incomplete. During re-review, ordered
  module reproduction showed the failure was timing-dependent even with engine disposal. Both
  concurrent sessions establish a MySQL `REPEATABLE READ` snapshot before the upsert; the
  duplicate updater's non-locking consistent read could therefore miss the newly inserted row.
- The post-upsert lookup is now a `SELECT ... FOR UPDATE` current read. The prior engine-disposal
  fixture was removed, the formerly failing ordered sequence passed twice, and the regression
  now repeats the concurrent path three times while proving both callers return the same single
  persisted card.
- `python -m pytest --cov=app --cov-report=term-missing`: 174 passed, 89% total coverage, with
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

## Re-review hardening

- TDD concurrency RED: two coordinated real MySQL sessions returned one success and one unique
  constraint `IntegrityError`. The bootstrap now uses validated MySQL `INSERT IGNORE` and its
  affected-row count, so simultaneous attempts complete normally as one created/one existing.
- Bootstrap credentials reuse the `UserCreate` 3..80 username and 8..128 password contract,
  reject whitespace-only passwords, and emit field-specific errors without credential values.
- Long passwords use a versioned `$autolava-bcrypt-sha256$v1$` format before bcrypt. Direct
  regressions cover 128 ASCII characters, a Unicode password exceeding 72 UTF-8 bytes, wrong
  passwords, the 255-character database field limit, and legacy raw bcrypt verification. A
  128-character bootstrapped administrator also logs in successfully.
- Compose exposes `AUTOLAVA_COOKIE_SECURE` with a secure `true` default. Deployment documentation
  requires external HTTPS termination in production and labels `false` as local HTTP evaluation
  only; the package remains exactly two containers.
- The CI container job provisions MySQL on the runner, reaches it from the API container through
  `host.docker.internal`, keeps explicit config/build gates, starts the release, validates Nginx,
  retries proxied `/health`, and always captures logs and tears down the stack.
- Re-review focused suite: 21 passed. Final gates: 174 backend tests with 89% coverage, Ruff clean,
  58 frontend tests, production build, and Playwright 3/3. Local Docker execution remained
  skipped because the Docker CLI is absent.
