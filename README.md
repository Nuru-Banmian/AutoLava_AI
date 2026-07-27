# AutoLava AI

AutoLava AI Phase 1 provides a FastAPI backend and React web application for multi-store
car-wash ledger, database, chart, and administration workflows.

## Windows local development

The local launcher uses one repository-local SQLite database, applies every migration through
`alembic upgrade head`, bootstraps the administrator, refreshes dependencies when their
manifests change, starts one FastAPI/Uvicorn worker and Vite, and opens
`http://127.0.0.1:5173`.

Install `uv`, Node.js, and npm, then run from PowerShell:

```powershell
.\scripts\start-local.ps1
```

The first run creates `.autolava-local`, installs missing dependencies, creates
`.autolava-local/autolava.sqlite3`, and asks for administrator credentials when they are absent.
The ignored root `.env` stores the local JWT and bootstrap credentials. Press `Ctrl+C` in the
launcher window to stop the two child processes. Use `-NoBrowser` when an automatic browser window
is not wanted.

There is no migration of old data. Existing data from an earlier runtime is intentionally not
imported; an empty database is migrated and bootstrapped by
`python -m app.scripts.create_admin`.

## Production deployment

Production runs exactly two services: `autolava-api` and `autolava-web`. The API runs one Uvicorn
worker. SQLite data is stored at `/data/autolava.sqlite3`, automatic backups are stored under
`/data/backups`, and the named `autolava_data` volume persists both directories. The application
keeps the latest three days of valid automatic backups.

Release images must be built in CI or on another build machine, saved, transferred to the server,
and loaded there. For example:

```sh
docker load -i autolava-api.tar
docker load -i autolava-web.tar
docker compose up -d --no-build
```

Do not run a production build on the 2-core/2-GB server. The Web image consumes an already-built
`frontend/dist`; it does not run Node during its image build.

1. Copy `.env.example` to `.env`.
2. Replace every `change-me` value. Use a long random JWT secret and a strong bootstrap password;
   configure the model profile fields, and do not commit `.env`.
3. Load both images, then run `docker compose up -d --no-build`.
4. Run the external HTTPS reverse proxy on the same host and forward it to `127.0.0.1:80`.

Compose binds Web only to loopback by default. The TLS proxy must replace untrusted inbound
`X-Forwarded-For` with the client address. Nginx accepts real-IP restoration only from loopback and
the Compose network's fixed `172.30.0.1` gateway. Production requires
`AUTOLAVA_COOKIE_SECURE=true`. For deliberate local HTTP evaluation only,
`AUTOLAVA_COOKIE_SECURE=false` may be used; never use it for an internet-accessible deployment.

The Agent model transport is selected with `AUTOLAVA_MODEL_ADAPTER`. CI uses the deterministic
`fake` adapter and never calls a provider. A production `openai_compatible` profile requires
`AUTOLAVA_MODEL_BASE_URL`, `AUTOLAVA_MODEL_ID`, `AUTOLAVA_MODEL_STRUCTURED_OUTPUT_METHOD`, and
`AUTOLAVA_MODEL_API_KEY`; no provider or model identifier is hard-coded in business code. Keep the
API key only in the ignored root `.env` or an injected deployment Secret, and never place it in
logs, error responses, frontend assets, or committed example values.

An optional fallback profile uses the corresponding `AUTOLAVA_FALLBACK_MODEL_*` fields. The API
retries only transient network, timeout, rate-limit, and provider 5xx failures once on the primary
model, then redoes that same model stage once on the fallback. Authentication, balance,
configuration, safety, permission, insufficient-information, and prompt-injection failures do not
switch providers. Provider/model pricing can be supplied with
`AUTOLAVA_MODEL_INPUT_COST_PER_MILLION` and `AUTOLAVA_MODEL_OUTPUT_COST_PER_MILLION` (and the
fallback equivalents) to estimate cost in conversation-free run statistics.

Production Agent access also requires a passing, redacted 2 GB release report at
`AUTOLAVA_AGENT_RELEASE_REPORT_PATH`. The report is evaluated against the exact provider, model,
fallback order, `AUTOLAVA_MODEL_TIMEOUT_SECONDS`, `AUTOLAVA_MODEL_MAX_OUTPUT_TOKENS`,
and `AUTOLAVA_AGENT_EVIDENCE_BATCH_LIMIT` (one normal batch, optionally one targeted supplemental
batch), plus the immutable deployed image digest in `AUTOLAVA_AGENT_RUNTIME_IMAGE_DIGEST`.
The report and its three verified evidence artifacts must share one directory. A missing, failed,
malformed, artifact-mismatched, image-mismatched, or profile-mismatched report keeps the Agent
globally disabled.
Each approved report has its own activation identity, so a newly approved or changed report remains
off until the final administrator explicitly enables that exact release. See
`docs/release/agent-release-evaluation.md` for the reproducible measurement method and current
release decision.

The API container runs Alembic before starting. On an empty volume it then creates the schema, and
the administrator bootstrap command is idempotent:

```sh
docker compose exec autolava-api python -m app.scripts.create_admin
```

If the bootstrap username already exists, the command does not change that account. After
confirming login, remove the bootstrap password from the runtime environment if the deployment
process supports secret rotation.

### Backup and manual recovery

Automatic SQLite backups run in the API process and retain three days. There is no in-app restore,
restore endpoint, or restore script.

Manual recovery is an operator-only emergency procedure: stop the API before replacing the main
database file, replace `/data/autolava.sqlite3` with a verified backup, remove stale
`autolava.sqlite3-wal` and `autolava.sqlite3-shm` companion files, and only then restart the API.
Replacing a live SQLite file can corrupt or discard committed data.

After deployment, record `docker stats --no-stream` once after the services have been idle and once
after one normal workflow (login, ledger read/write, and chart load). Keep both snapshots with the
release notes so later Agent or automation design uses measured remaining memory.

## Verification

Backend checks use a disposable SQLite file:

```powershell
cd backend
$env:AUTOLAVA_DATABASE_PATH = Join-Path $env:TEMP "autolava-test.sqlite3"
ruff check .
pytest --cov=app --cov-report=term-missing
```

Frontend verification uses the lockfile and Playwright Chromium:

```sh
cd frontend
npm ci
npm test
npm run build
npx playwright install chromium
npx playwright test
```

CI builds `frontend/dist`, builds the API and prebuilt Web images, validates
`docker compose config`, starts them with `docker compose up -d --no-build`, and checks Nginx plus
the proxied API health endpoint.
