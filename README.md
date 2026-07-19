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
