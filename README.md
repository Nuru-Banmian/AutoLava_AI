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

Run the manual **Build release images** workflow for a release commit, or run
`bash scripts/build-release-images.sh` on a Linux build machine with Docker and Node 22. The API
build uses `backend/uv.lock` with `uv sync --locked --no-dev --no-editable`; a mismatch between the
lock and `pyproject.toml` fails the build. The script builds the Web bundle with `npm ci`, labels
both images with the source commit, starts the API image against a disposable Docker volume, checks
health and the migrated Alembic revision, and compares the packages actually installed in the
Linux/Python image with the target-selected production dependency tree from the lock. The manual
workflow saves the two images and this evidence as one artifact.
The dependency list describes the target image; the full multi-platform lock file is not an
installed-package list. The script excludes test tools and Windows-only `tzdata` from that image.
This image check does not cover the browser login and ledger flow; that requires a separate
release validation. Build from a clean committed checkout. Load the saved images on the production
server, set `AUTOLAVA_API_IMAGE` and `AUTOLAVA_WEB_IMAGE` to the commit-tagged images, and keep using
`docker compose up -d --no-build`.

1. Copy `.env.example` to `.env`.
2. Replace every `change-me` value. Use a long random JWT secret and a strong bootstrap password;
   do not commit `.env`.
3. Load both images, then run `docker compose up -d --no-build`.
4. Run the external HTTPS reverse proxy on the same host and forward it to `127.0.0.1:80`.

Compose binds Web only to loopback by default. The TLS proxy must replace untrusted inbound
`X-Forwarded-For` with the client address. Nginx accepts real-IP restoration only from loopback and
the Compose network's fixed `172.30.0.1` gateway. Production requires
`AUTOLAVA_COOKIE_SECURE=true`. For deliberate local HTTP evaluation only,
`AUTOLAVA_COOKIE_SECURE=false` may be used; never use it for an internet-accessible deployment.

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
release notes so later automation design uses measured remaining memory.

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

The normal PR CI runs backend and frontend checks, including the locked backend install and
`npm ci`. The separate manual `release-flow.yml` workflow builds both images and exercises
the published Web bundle through real Nginx and a local HTTPS test proxy. It validates Secure
Cookie login and logout, browser ledger save and restart readback, HTTP analytics and workbook
export, and migration of a disposable older database. Image IDs, migration versions, selected
runtime dependencies, browser traces, and failure logs are saved with the run. The local HTTPS
certificate is self-signed and trusted only by this isolated check. See
`docs/validation/issue-203-release-flow.md` for its evidence boundary.
