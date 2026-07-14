# AutoLava AI

AutoLava AI Phase 1 provides a FastAPI backend and React web application for multi-store
car-wash ledger, database, chart, and administration workflows.

## Production deployment

The release package runs exactly two containers: `autolava-api` and `autolava-web`. MySQL is
not included. Create the application database and user on the deployment host, and ensure the
database accepts connections from Docker through `host.docker.internal`.

1. Copy `.env.example` to `.env`.
2. Replace every `change-me` value. Use a long random JWT secret and a strong bootstrap
   password; do not commit `.env`.
3. Terminate HTTPS in a production reverse proxy or load balancer before traffic reaches the
   published web port. Production requires `AUTOLAVA_COOKIE_SECURE=true` so browsers send the
   authentication cookie only over HTTPS.
4. Start the release:

   ```sh
   docker compose up -d --build
   ```

The API container applies Alembic migrations before starting. The web container serves the
single-page application on port 80 and proxies `/api/` and `/health` to the API.

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
