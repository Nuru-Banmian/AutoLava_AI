# AutoLava AI

AutoLava AI Phase 1 provides a FastAPI backend and React web application for multi-store
car-wash ledger, database, chart, and administration workflows.

## Windows local development

The reusable local launcher supports the current Phase 1 application and remains the entry point
for planned Phase 2 workforce, Phase 3 agent, and Phase 4 automation features. It reuses the local
MySQL service, applies every migration through `alembic upgrade head`, refreshes dependencies when
their manifests change, starts FastAPI and Vite, and opens `http://127.0.0.1:5173`.

Keep the SQLAlchemy database URL in the ignored `.autolava-db.env`. The launcher creates or reuses
the ignored root `.env` for the local JWT and administrator credentials. Later-phase model keys and
other `AUTOLAVA_*` settings also belong in `.env`; the launcher passes them through without needing
a code change. Never commit either environment file.

Run from PowerShell:

```powershell
.\scripts\start-local.ps1
```

The first run installs missing dependencies and asks for administrator credentials only when they
are absent. Later runs reuse the saved local values. Press `Ctrl+C` in the launcher window to stop
both services. Use `-NoBrowser` when an automatic browser window is not wanted.

Keep normal local data in a dedicated database such as `autolava_local`. The launcher rejects a
database whose name ends in `_test`, because backend tests clear `autolava_test`. The
`-AllowTestDatabase` switch exists only for explicit test/debug sessions and must not be used with
real operating data.

Create a credential-safe backup before migrations or data cleanup:

```powershell
.\scripts\backup-local-db.ps1
```

Backups are written under the ignored `.autolava-local\backups` directory. Restore a verified
backup into the local runtime database with:

```powershell
.\scripts\restore-local-db.ps1 `
  -BackupPath .\.autolava-local\backups\autolava_test-YYYYMMDD-HHMMSS.sql `
  -TargetDatabase autolava_local
```

The restore command refuses test-database targets and non-empty targets unless `-Force` is supplied.
After a successful restore it updates the ignored `.autolava-db.env` to the restored database name
without printing credentials.

## Production deployment

The release package runs exactly two containers: `autolava-api` and `autolava-web`. MySQL is
not included. Create the application database and user on the deployment host, and ensure the
database accepts connections from Docker through `host.docker.internal`.

1. Copy `.env.example` to `.env`.
2. Replace every `change-me` value. Use a long random JWT secret and a strong bootstrap
   password; do not commit `.env`.
3. Run the external HTTPS reverse proxy on the same host and forward to `127.0.0.1:80`.
   Compose binds the web container only to that loopback address; direct internet exposure is
   not the production topology. The TLS proxy must replace (not append an untrusted inbound)
   `X-Forwarded-For` with the client address. Nginx accepts real-IP restoration only from
   loopback and the Compose network's fixed `172.30.0.1` gateway, resolves the chain recursively,
   and keys login limiting on the restored address. Do not broaden `set_real_ip_from` to public
   networks. Production requires `AUTOLAVA_COOKIE_SECURE=true` so browsers send the
   authentication cookie only over HTTPS.
4. Start the release:

   ```sh
   docker compose up -d --build
   ```

The API container applies Alembic migrations before starting. The web container serves the
single-page application on port 80 and proxies `/api/` and `/health` to the API.
The API is not published directly; the loopback-bound web container is the enforced trusted ingress and uses
a bounded 10 MiB Nginx shared-memory zone to rate-limit `/api/auth/login` per client IP (five
requests per minute with a burst of five). Keep the API container private behind this proxy.
Production startup rejects missing, example, short JWT secrets and default database passwords.

For deliberate local HTTP evaluation only, set `AUTOLAVA_COOKIE_SECURE=false`. This weakens
cookie transport security and must not be used for an internet-accessible or production
deployment. Compose intentionally remains a two-container package and does not add a TLS or
database container.

## First administrator

After the containers are healthy, create the first administrator from the values in `.env`:

```sh
docker compose exec autolava-api python -m app.scripts.create_admin
```

The command is idempotent. If `AUTOLAVA_BOOTSTRAP_USERNAME` already exists, it exits
successfully without changing that account, including its password, role, or active state.
After confirming login, remove the bootstrap password from the runtime environment if your
deployment process supports secret rotation.

## Local verification

Backend commands must run with the project environment and a dedicated `autolava_test` MySQL
database configured through `AUTOLAVA_DATABASE_URL`:

```sh
cd backend
ruff check .
pytest --cov=app --cov-report=term-missing
```

Frontend verification uses the lockfile and the installed Playwright Chromium browser:

```sh
cd frontend
npm ci
npm test
npm run build
npx playwright install chromium
npx playwright test
```

CI additionally validates and builds both container images with `docker compose config` and
`docker compose build`.
