# AutoLava AI Phase 1 Foundation Implementation Plan

> **Execution note:** Work through this roadmap task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy the complete non-AI operating system for authentication, store-scoped administration, daily ledger entry, audit/rollback, export, weather, dashboard briefings, and charts.

**Architecture:** Use a monorepo with a FastAPI REST API and a React single-page application. Business mutations live in transaction-scoped backend services, store authorization is enforced by dependencies before those services run, and every critical mutation records a complete audit snapshot. The browser consumes typed JSON APIs; weather failure remains non-blocking and MySQL stays outside the deployment compose stack.

**Tech Stack:** Python, FastAPI, SQLAlchemy 2.x, Alembic, MySQL, pytest, React, TypeScript, Vite, shadcn/ui, Tailwind CSS, Recharts, Vitest, React Testing Library, Playwright, APScheduler, Docker Compose.

## Global Constraints

- Artificial intelligence is not required for any Phase 1 workflow.
- Roles are exactly `admin` and `user`; users are created by administrators and are enabled/disabled rather than physically deleted.
- User-store authorization is binary through `store_members`; unauthorized stores are invisible.
- Store, worker, and used income-category records are disabled rather than physically deleted.
- Store time zones are independent; the deployed default use case is Italy and examples use `Europe/Rome`.
- Renaming or relocating a store never rewrites historical ledger or weather rows; new coordinates affect only later lookups and explicit compensation of missing automatic fields.
- `store_id + date`, `store_id + user_id`, and `store_id + card_type` are unique where defined by the spec.
- Daily revenue is always recomputed from active or historical items whose category has `include_in_total = true`; clients cannot set it.
- Ledger dates cannot be in the future according to the selected store's local date.
- Weather lookup failure never blocks ledger saving and background refresh never overwrites user-edited final weather.
- All create, update, delete, and rollback operations are audited with full before/after snapshots.
- Docker runs only `autolava-api` and `autolava-web`; MySQL runs on the server host.
- Phase 1 does not include 7-day home charts, cross-store chart comparisons, PDF/image exports, public registration, or AI endpoints.
- The four-phase release does not add costs/expenses, multilingual UI, PWA/native packaging, email/SMS/Telegram notifications, a memory-management page, overtime multipliers, decimal hours, or clock-in/out tracking.

---

## File Structure

```text
.
├── .env.example                         # deploy-time variables without secrets
├── .github/workflows/ci.yml             # backend, frontend, and browser verification
├── compose.yaml                         # api and web only; no MySQL service
├── backend/
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── pyproject.toml
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/0001_phase_1.py
│   ├── app/
│   │   ├── main.py
│   │   ├── api/deps.py
│   │   ├── api/router.py
│   │   ├── api/routes/{auth,admin,ledger,database,charts,dashboard}.py
│   │   ├── core/{config,database,security}.py
│   │   ├── models/{base,identity,ledger,audit,operations}.py
│   │   ├── schemas/{auth,admin,ledger,database,charts,dashboard}.py
│   │   └── services/{access,audit,ledger,rollback,export,weather,briefing,analytics,scheduler}.py
│   └── tests/
│       ├── conftest.py
│       ├── api/{test_auth,test_admin,test_ledger,test_database,test_charts,test_dashboard}.py
│       └── services/{test_ledger,test_rollback,test_weather,test_briefing,test_analytics}.py
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── playwright.config.ts
    ├── src/
    │   ├── main.tsx
    │   ├── router.tsx
    │   ├── api/{client,types}.ts
    │   ├── auth/AuthProvider.tsx
    │   ├── stores/StoreProvider.tsx
    │   ├── layouts/AppShell.tsx
    │   ├── pages/{Login,Home,Ledger,Database,Charts,Admin}Page.tsx
    │   └── components/{StorePicker,BriefingCards,LedgerForm,RecordTable,ChartPanel}.tsx
    └── tests/{auth,ledger,database,charts,responsive}.spec.ts
```

## Shared API contracts

```text
POST   /api/auth/login
POST   /api/auth/logout
GET    /api/auth/me
GET    /api/stores/accessible
GET    /api/admin/{users,stores,income-categories,alerts,task-logs}
POST   /api/admin/{users,stores,income-categories}
PATCH  /api/admin/{users,stores,income-categories}/{id}
PUT    /api/admin/stores/{store_id}/members
GET    /api/admin/stores/{store_id}/members
GET    /api/admin/users/{user_id}/operations
GET    /api/admin/stores/geocode?query=
GET    /api/ledger/{store_id}?date=YYYY-MM-DD
PUT    /api/ledger/{store_id}/{date}
DELETE /api/ledger/{store_id}/{date}
GET    /api/database/{store_id}/records
GET    /api/database/{store_id}/history
POST   /api/database/{store_id}/history/{audit_id}/rollback
GET    /api/database/{store_id}/export.xlsx
GET    /api/weather/{store_id}/{date}
GET    /api/dashboard/{store_id}
POST   /api/dashboard/{store_id}/refresh
GET    /api/charts/{store_id}
```

### Task 1: Bootstrap the monorepo and executable API/UI shells

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/main.py`
- Create: `backend/app/core/config.py`
- Create: `backend/tests/test_health.py`
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/App.test.tsx`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/components.json`
- Create: `frontend/src/index.css`
- Create: `frontend/src/components/ui/`

**Interfaces:**
- Consumes: environment variables prefixed `AUTOLAVA_`.
- Produces: `create_app() -> FastAPI`, `GET /health -> {"status":"ok"}`, and a React root that renders `AutoLava AI`.

- [ ] **Step 1: Add the backend package metadata and failing health test**

```toml
# backend/pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "autolava-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "alembic",
  "apscheduler",
  "aiosqlite",
  "bcrypt",
  "fastapi",
  "httpx",
  "openpyxl",
  "pydantic-settings",
  "pyjwt",
  "sqlalchemy>=2,<3",
  "uvicorn[standard]",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "pytest-cov", "pyyaml", "respx", "ruff"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

```python
# backend/tests/test_health.py
from fastapi.testclient import TestClient

from app.main import create_app


def test_health() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the backend test and verify the missing app failure**

Run: `cd backend && python -m pip install -e ".[dev]" && pytest tests/test_health.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Implement configuration and the app factory**

```python
# backend/app/core/config.py
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOLAVA_", env_file=".env")

    environment: str = "development"
    database_path: Path = Path("../.autolava-local/autolava.sqlite3")
    jwt_secret: SecretStr = SecretStr("development-only-secret")
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AutoLava AI API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 4: Add and verify the minimal React shell**

```json
// frontend/package.json
{
  "name": "autolava-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "@radix-ui/react-alert-dialog": "latest",
    "@radix-ui/react-dialog": "latest",
    "@radix-ui/react-select": "latest",
    "@radix-ui/react-tabs": "latest",
    "@hookform/resolvers": "latest",
    "@tanstack/react-query": "latest",
    "class-variance-authority": "latest",
    "clsx": "latest",
    "date-fns": "latest",
    "lucide-react": "latest",
    "react": "latest",
    "react-dom": "latest",
    "react-hook-form": "latest",
    "react-router-dom": "latest",
    "recharts": "latest",
    "tailwind-merge": "latest",
    "zod": "latest"
  },
  "devDependencies": {
    "@playwright/test": "latest",
    "@testing-library/jest-dom": "latest",
    "@testing-library/react": "latest",
    "@types/react": "latest",
    "@types/react-dom": "latest",
    "@vitejs/plugin-react": "latest",
    "@tailwindcss/vite": "latest",
    "jsdom": "latest",
    "msw": "latest",
    "typescript": "latest",
    "tailwindcss": "latest",
    "vite": "latest",
    "vitest": "latest"
  }
}
```

```tsx
// frontend/src/App.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders the product name", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "AutoLava AI" })).toBeInTheDocument();
  });
});
```

```tsx
// frontend/src/App.tsx
export default function App() {
  return <h1>AutoLava AI</h1>;
}
```

```tsx
// frontend/src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>,
);
```

Configure Tailwind through `@tailwindcss/vite`, import `src/index.css` from `main.tsx`, set shadcn aliases `@/components`, `@/lib`, `@/hooks`, and add the shadcn `button`, `input`, `select`, `dialog`, `alert-dialog`, `tabs`, `card`, `table`, `sheet`, and `form` source files under `frontend/src/components/ui/`. These checked-in components are the primitives used by later tasks; do not introduce a runtime shadcn package.

Run: `cd frontend && npm install && npm test && npm run build`

Expected: one Vitest test passes and Vite produces `dist/`.

- [ ] **Step 5: Commit the executable shells**

```bash
git add backend frontend
git commit -m "build: bootstrap api and web applications"
```

### Task 2: Create the Phase 1 database schema and migration

**Files:**
- Create: `backend/app/core/database.py`
- Create: `backend/app/models/base.py`
- Create: `backend/app/models/identity.py`
- Create: `backend/app/models/ledger.py`
- Create: `backend/app/models/audit.py`
- Create: `backend/app/models/operations.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0001_phase_1.py`
- Create: `backend/tests/test_schema.py`

**Interfaces:**
- Consumes: `Settings.database_url`.
- Produces: `async_session_factory`, `get_session()`, SQLAlchemy models for `users`, `stores`, `store_members`, `store_settings`, `income_categories`, `store_daily_records`, `daily_income_items`, `audit_log`, `daily_briefings`, `scheduled_task_logs`, and `system_alerts`.

- [ ] **Step 1: Write schema assertions before defining models**

```python
# backend/tests/test_schema.py
from app.models.base import Base
import app.models.audit  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.ledger  # noqa: F401
import app.models.operations  # noqa: F401


def test_phase_one_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users", "stores", "store_members", "store_settings",
        "income_categories", "store_daily_records", "daily_income_items",
        "audit_log", "daily_briefings", "scheduled_task_logs", "system_alerts",
    }


def test_business_unique_constraints_exist() -> None:
    assert {c.name for c in Base.metadata.tables["store_members"].constraints} >= {
        "uq_store_members_store_user"
    }
    assert {c.name for c in Base.metadata.tables["store_daily_records"].constraints} >= {
        "uq_store_daily_records_store_date"
    }
```

- [ ] **Step 2: Run the schema test and verify it fails**

Run: `cd backend && pytest tests/test_schema.py -q`

Expected: FAIL because `app.models` has not been created.

- [ ] **Step 3: Define the base, session, identity, and ledger models**

```python
# backend/app/models/base.py
from datetime import datetime
from typing import Annotated

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, mapped_column

timestamp = Annotated[datetime, mapped_column(DateTime(timezone=True))]


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })
```

```python
# backend/app/core/database.py
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
```

```python
# backend/app/models/identity.py
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    remember_token: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    __table_args__ = (CheckConstraint("role in ('admin','user')", name="role"),)


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(255))
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Rome")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class StoreMember(Base):
    __tablename__ = "store_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (UniqueConstraint("store_id", "user_id", name="uq_store_members_store_user"),)

```

```python
# backend/app/models/ledger.py
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class IncomeCategory(Base):
    __tablename__ = "income_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    name: Mapped[str] = mapped_column(String(100))
    include_in_total: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class StoreDailyRecord(Base):
    __tablename__ = "store_daily_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    date: Mapped[date] = mapped_column(Date)
    daily_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    wash_count: Mapped[int | None]
    is_open: Mapped[str] = mapped_column(String(20))
    weather: Mapped[str | None] = mapped_column(String(50))
    weather_auto: Mapped[str | None] = mapped_column(String(50))
    weather_code: Mapped[int | None]
    temperature_max: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    temperature_min: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    precipitation: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    activity: Mapped[str | None] = mapped_column(Text)
    weather_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    items: Mapped[list["DailyIncomeItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (
        UniqueConstraint("store_id", "date", name="uq_store_daily_records_store_date"),
        CheckConstraint("is_open in ('营业','休息','天气停业')", name="open_status"),
    )


class DailyIncomeItem(Base):
    __tablename__ = "daily_income_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("store_daily_records.id", ondelete="CASCADE"))
    category_id: Mapped[int] = mapped_column(ForeignKey("income_categories.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("record_id", "category_id"),)
```

- [ ] **Step 4: Define operations/audit models, generate the migration, and verify MySQL upgrade**

```python
# backend/app/models/audit.py
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    operation_domain: Mapped[str] = mapped_column(String(30))
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"))
    record_id: Mapped[int | None]
    record_date: Mapped[date | None] = mapped_column(Date)
    operation_type: Mapped[str] = mapped_column(String(20))
    operation_source: Mapped[str] = mapped_column(String(20))
    operator_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(Text)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

```python
# backend/app/models/operations.py
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailyBriefing(Base):
    __tablename__ = "daily_briefings"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    card_type: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (UniqueConstraint("store_id", "card_type", name="uq_daily_briefings_store_card"),)


class ScheduledTaskLog(Base):
    __tablename__ = "scheduled_task_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"))
    task_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SystemAlert(Base):
    __tablename__ = "system_alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"))
    alert_type: Mapped[str] = mapped_column(String(60))
    level: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None]
```

Run: `cd backend && alembic revision --autogenerate -m "phase 1 schema" && alembic upgrade head && pytest tests/test_schema.py -q`

Expected: migration creates all 11 tables in the configured MySQL test database and both schema tests pass. Rename the generated revision file to `0001_phase_1.py` while preserving its generated `revision` identifier.

- [ ] **Step 5: Commit the schema foundation**

```bash
git add backend/app/core/database.py backend/app/models backend/alembic.ini backend/alembic backend/tests/test_schema.py
git commit -m "feat: add phase one database schema"
```

### Task 3: Implement cookie authentication and store-scoped authorization

**Files:**
- Create: `backend/app/core/security.py`
- Create: `backend/app/api/deps.py`
- Create: `backend/app/schemas/auth.py`
- Create: `backend/app/services/access.py`
- Create: `backend/app/api/routes/auth.py`
- Create: `backend/app/api/router.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_auth.py`

**Interfaces:**
- Consumes: `User`, `Store`, `StoreMember`, database sessions, and `Settings.jwt_secret`.
- Produces: `hash_password(str) -> str`, `verify_password(str, str) -> bool`, `create_access_token(user_id: int, remember: bool) -> tuple[str, int]`, `get_current_user() -> User`, `require_admin() -> User`, and `require_store_access(store_id: int) -> StoreAccess`.

- [ ] **Step 1: Write failing authentication and isolation tests**

```python
# backend/tests/api/test_auth.py
async def test_login_sets_http_only_cookie(client, user_factory) -> None:
    await user_factory(username="maria", password="secret", role="user")
    response = await client.post("/api/auth/login", json={
        "username": "maria", "password": "secret", "remember": True,
    })
    assert response.status_code == 200
    assert response.json()["username"] == "maria"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Max-Age=2592000" in response.headers["set-cookie"]


async def test_disabled_user_cannot_login(client, user_factory) -> None:
    await user_factory(username="disabled", password="secret", is_active=False)
    response = await client.post("/api/auth/login", json={
        "username": "disabled", "password": "secret", "remember": False,
    })
    assert response.status_code == 401


async def test_unassigned_store_is_not_exposed(auth_client, store_factory) -> None:
    hidden = await store_factory(name="Hidden")
    response = await auth_client.get("/api/stores/accessible")
    assert response.status_code == 200
    assert hidden.id not in {store["id"] for store in response.json()}
```

- [ ] **Step 2: Run the focused tests and verify route failures**

Run: `cd backend && pytest tests/api/test_auth.py -q`

Expected: FAIL because `/api/auth/login` and `/api/stores/accessible` return 404.

- [ ] **Step 3: Implement password/JWT primitives and authorization dependencies**

```python
# backend/app/core/security.py
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: int, remember: bool) -> tuple[str, int]:
    max_age = 30 * 24 * 3600 if remember else 12 * 3600
    payload = {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(seconds=max_age)}
    secret = get_settings().jwt_secret.get_secret_value()
    return jwt.encode(payload, secret, algorithm="HS256"), max_age


def decode_access_token(token: str) -> int:
    secret = get_settings().jwt_secret.get_secret_value()
    return int(jwt.decode(token, secret, algorithms=["HS256"])["sub"])
```

```python
# backend/app/api/deps.py
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import decode_access_token
from app.models.identity import Store, StoreMember, User

Session = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(session: Session, access_token: str | None = Cookie(None)) -> User:
    try:
        user_id = decode_access_token(access_token or "")
    except Exception as exc:
        raise HTTPException(401, "Authentication required") from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Authentication required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return user


@dataclass(frozen=True)
class StoreAccess:
    store: Store
    user: User


async def require_store_access(store_id: int, user: CurrentUser, session: Session) -> StoreAccess:
    store = await session.get(Store, store_id)
    if store is None or not store.is_active:
        raise HTTPException(404, "Store not found")
    allowed = user.role == "admin" or await session.scalar(
        select(exists().where(StoreMember.store_id == store_id, StoreMember.user_id == user.id))
    )
    if not allowed:
        raise HTTPException(404, "Store not found")
    return StoreAccess(store=store, user=user)
```

- [ ] **Step 4: Implement auth/access routes and verify all auth tests**

```python
# backend/app/api/routes/auth.py
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.core.config import get_settings
from app.core.security import create_access_token, verify_password
from app.models.identity import Store, StoreMember, User

router = APIRouter(tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str
    remember: bool = False


@router.post("/auth/login")
async def login(body: LoginBody, response: Response, session: Session) -> dict:
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    token, max_age = create_access_token(user.id, body.remember)
    response.set_cookie(
        "access_token", token, httponly=True, secure=get_settings().cookie_secure,
        samesite="lax", max_age=max_age, path="/",
    )
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/auth/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie("access_token", path="/")


@router.get("/auth/me")
async def me(user: CurrentUser) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/stores/accessible")
async def accessible_stores(user: CurrentUser, session: Session) -> list[dict]:
    query = select(Store).where(Store.is_active.is_(True)).order_by(Store.name)
    if user.role != "admin":
        query = query.join(StoreMember).where(StoreMember.user_id == user.id)
    stores = (await session.scalars(query)).all()
    return [{"id": s.id, "name": s.name, "timezone": s.timezone} for s in stores]
```

Run: `cd backend && pytest tests/api/test_auth.py -q`

Expected: all authentication, disabled-user, and hidden-store tests pass.

- [ ] **Step 5: Commit authentication and access control**

```bash
git add backend/app backend/tests/api/test_auth.py
git commit -m "feat: add authentication and store access control"
```

### Task 4: Build administrator configuration APIs

**Files:**
- Create: `backend/app/schemas/admin.py`
- Create: `backend/app/api/routes/admin.py`
- Create: `backend/app/services/audit.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/api/test_admin.py`

**Interfaces:**
- Consumes: `require_admin`, identity/ledger models, and `hash_password`.
- Produces: CRUD-with-disable endpoints for users, stores, memberships, and income categories; no public registration and no hard delete endpoint.

- [ ] **Step 1: Write failing admin behavior tests**

```python
# backend/tests/api/test_admin.py
async def test_regular_user_cannot_create_user(auth_client) -> None:
    response = await auth_client.post("/api/admin/users", json={
        "username": "new-user", "password": "secret", "role": "user",
    })
    assert response.status_code == 403


async def test_admin_can_assign_exact_store_members(admin_client, user_factory, store_factory) -> None:
    user = await user_factory(username="family")
    first = await store_factory(name="First")
    second = await store_factory(name="Second")
    response = await admin_client.put(f"/api/admin/stores/{first.id}/members", json={
        "user_ids": [user.id],
    })
    assert response.status_code == 200
    assert response.json() == {"store_id": first.id, "user_ids": [user.id]}
    accessible = await admin_client.get(f"/api/admin/users/{user.id}/stores")
    assert [item["id"] for item in accessible.json()] == [first.id]
    assert second.id not in [item["id"] for item in accessible.json()]


async def test_used_income_category_can_only_be_disabled(admin_client, category_with_item) -> None:
    response = await admin_client.delete(f"/api/admin/income-categories/{category_with_item.id}")
    assert response.status_code == 409
    response = await admin_client.patch(
        f"/api/admin/income-categories/{category_with_item.id}", json={"is_active": False},
    )
    assert response.status_code == 200
```

- [ ] **Step 2: Run admin tests and verify the routes are absent**

Run: `cd backend && pytest tests/api/test_admin.py -q`

Expected: FAIL with 404 responses for admin routes.

- [ ] **Step 3: Add request schemas and user/store/category endpoints**

```python
# backend/app/schemas/admin.py
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "user"] = "user"


class UserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool | None = None


class StoreCreate(BaseModel):
    name: str
    address: str
    latitude: Decimal
    longitude: Decimal
    timezone: str = "Europe/Rome"


class StorePatch(BaseModel):
    name: str | None = None
    address: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    timezone: str | None = None
    is_active: bool | None = None


class MemberReplace(BaseModel):
    user_ids: list[int]


class CategoryCreate(BaseModel):
    store_id: int
    name: str
    include_in_total: bool
    sort_order: int = 0


class CategoryPatch(BaseModel):
    name: str | None = None
    include_in_total: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None
```

```python
# backend/app/api/routes/admin.py (core route pattern; apply identically to stores/categories)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select

from app.api.deps import Session, require_admin
from app.core.security import hash_password
from app.models.identity import Store, StoreMember, User
from app.models.ledger import DailyIncomeItem, IncomeCategory
from app.schemas.admin import CategoryCreate, CategoryPatch, MemberReplace, StoreCreate, StorePatch, UserCreate, UserPatch

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/users", status_code=201)
async def create_user(body: UserCreate, session: Session) -> dict:
    user = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    session.add(user)
    await session.commit()
    return {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active}


@router.patch("/users/{user_id}")
async def patch_user(user_id: int, body: UserPatch, session: Session) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.is_active is not None:
        user.is_active = body.is_active
    await session.commit()
    return {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active}


@router.put("/stores/{store_id}/members")
async def replace_members(store_id: int, body: MemberReplace, session: Session) -> dict:
    if await session.get(Store, store_id) is None:
        raise HTTPException(404, "Store not found")
    await session.execute(delete(StoreMember).where(StoreMember.store_id == store_id))
    session.add_all(StoreMember(store_id=store_id, user_id=user_id) for user_id in sorted(set(body.user_ids)))
    await session.commit()
    return {"store_id": store_id, "user_ids": sorted(set(body.user_ids))}


@router.delete("/income-categories/{category_id}", status_code=204)
async def delete_unused_category(category_id: int, session: Session) -> None:
    category = await session.get(IncomeCategory, category_id)
    if category is None:
        raise HTTPException(404, "Category not found")
    used = await session.scalar(select(DailyIncomeItem.id).where(DailyIncomeItem.category_id == category_id).limit(1))
    if used is not None:
        raise HTTPException(409, "Used categories must be disabled")
    await session.delete(category)
    await session.commit()
```

- [ ] **Step 4: Complete the symmetric list/create/patch routes and run tests**

```python
# backend/app/services/audit.py (generic administrator helper)
from typing import Any

from app.models.audit import AuditLog


def add_admin_audit(session, *, actor_id: int, store_id: int | None,
                    record_id: int | None, operation_type: str,
                    description: str, before: dict[str, Any] | None,
                    after: dict[str, Any] | None) -> AuditLog:
    entry = AuditLog(
        operation_domain="admin", store_id=store_id, record_id=record_id,
        record_date=None, operation_type=operation_type, operation_source="manual",
        operator_user_id=actor_id, before_json=before, after_json=after,
        description=description, requires_approval=False, approved=True,
    )
    session.add(entry)
    return entry
```

Complete these exact operations in `admin.py`: `GET /users`, `GET /users/{id}/stores`, `GET /users/{id}/operations`, `POST/PATCH /stores`, `GET /stores`, `GET /stores/{id}/members`, `POST/PATCH/DELETE /income-categories`, `GET /income-categories?store_id=`, `GET /alerts`, and `GET /task-logs`. Every lookup returns 404 when absent; list routes order by display name or `sort_order,id`. Every mutation calls `add_admin_audit` before commit; password snapshots contain only `{"password_changed": true}` and never a hash. When `include_in_total` changes, lock every affected daily record, snapshot it, recompute `daily_revenue`, and add one `operation_domain=ledger`, `operation_source=system` audit per affected record in the same transaction so stored historical totals cannot become stale.

Run: `cd backend && pytest tests/api/test_admin.py -q`

Expected: regular users receive 403, admins can create/configure/disable entities, membership replacement is exact, and used categories return 409 on delete.

- [ ] **Step 5: Commit administrator APIs**

```bash
git add backend/app/schemas/admin.py backend/app/api/routes/admin.py backend/app/api/router.py backend/tests/api/test_admin.py
git commit -m "feat: add administrator configuration APIs"
```

### Task 5: Implement transactional ledger writes and complete audit snapshots

**Files:**
- Create: `backend/app/schemas/ledger.py`
- Modify: `backend/app/services/audit.py`
- Create: `backend/app/services/ledger.py`
- Create: `backend/app/api/routes/ledger.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/services/test_ledger.py`
- Create: `backend/tests/api/test_ledger.py`

**Interfaces:**
- Consumes: `StoreAccess`, active/historical income categories, and store-local current date.
- Produces: `LedgerService.upsert(store: Store, record_date: date, payload: dict, actor: User, overwrite: bool = False, source: str = "manual", requires_approval: bool = False, approved: bool = True) -> tuple[StoreDailyRecord, bool]`, `LedgerService.delete(...)`, and canonical `record_snapshot(record) -> dict`.

- [ ] **Step 1: Write failing revenue, future-date, overwrite, and audit tests**

```python
# backend/tests/services/test_ledger.py
from datetime import date
from decimal import Decimal


async def test_revenue_uses_only_included_categories(ledger_service, ledger_context) -> None:
    record = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=date(2026, 7, 13),
        payload={
            "is_open": "营业", "wash_count": 12, "weather": "晴", "activity": None,
            "items": [
                {"category_id": ledger_context.cash.id, "amount": "200.00"},
                {"category_id": ledger_context.card.id, "amount": "150.00"},
                {"category_id": ledger_context.hidden.id, "amount": "80.00"},
            ],
        },
        actor=ledger_context.user,
    )
    assert record.daily_revenue == Decimal("350.00")


async def test_update_writes_before_and_after_snapshots(ledger_service, ledger_context, audit_repo) -> None:
    first = await ledger_service.upsert_from_fixture(ledger_context, cash="100.00")
    await ledger_service.upsert_from_fixture(ledger_context, cash="120.00", overwrite=True)
    audit = await audit_repo.latest(record_id=first.id)
    assert audit.operation_type == "update"
    assert audit.before_json["items"][0]["amount"] == "100.00"
    assert audit.after_json["items"][0]["amount"] == "120.00"
```

```python
# backend/tests/api/test_ledger.py
async def test_same_date_requires_overwrite_flag(auth_client, assigned_store, ledger_payload) -> None:
    path = f"/api/ledger/{assigned_store.id}/2026-07-13"
    assert (await auth_client.put(path, json=ledger_payload)).status_code == 201
    response = await auth_client.put(path, json=ledger_payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "Record exists; confirm overwrite"
    assert (await auth_client.put(path + "?overwrite=true", json=ledger_payload)).status_code == 200
```

- [ ] **Step 2: Run focused tests and verify missing service/route failures**

Run: `cd backend && pytest tests/services/test_ledger.py tests/api/test_ledger.py -q`

Expected: FAIL because `LedgerService` and ledger routes do not exist.

- [ ] **Step 3: Implement canonical snapshots and revenue recomputation**

```python
# backend/app/services/audit.py
from decimal import Decimal

from app.models.audit import AuditLog
from app.models.ledger import StoreDailyRecord


def record_snapshot(record: StoreDailyRecord) -> dict:
    return {
        "id": record.id,
        "store_id": record.store_id,
        "date": record.date.isoformat(),
        "daily_revenue": str(record.daily_revenue),
        "wash_count": record.wash_count,
        "is_open": record.is_open,
        "weather": record.weather,
        "weather_auto": record.weather_auto,
        "weather_code": record.weather_code,
        "temperature_max": None if record.temperature_max is None else str(record.temperature_max),
        "temperature_min": None if record.temperature_min is None else str(record.temperature_min),
        "precipitation": None if record.precipitation is None else str(record.precipitation),
        "activity": record.activity,
        "weather_edited": record.weather_edited,
        "scanned": record.scanned,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "items": [
            {
                "id": item.id,
                "category_id": item.category_id,
                "amount": str(item.amount),
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in sorted(record.items, key=lambda value: value.category_id)
        ],
    }


def make_ledger_audit(*, record: StoreDailyRecord, operation_type: str, source: str,
                      user_id: int, before: dict | None, after: dict | None,
                      requires_approval: bool = False, approved: bool = True) -> AuditLog:
    return AuditLog(
        operation_domain="ledger", store_id=record.store_id, record_id=record.id,
        record_date=record.date, operation_type=operation_type, operation_source=source,
        operator_user_id=user_id, before_json=before, after_json=after,
        description=f"Ledger {operation_type} for {record.date.isoformat()}",
        requires_approval=requires_approval, approved=approved,
    )
```

```python
# backend/app/services/ledger.py
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.services.audit import make_ledger_audit, record_snapshot


class LedgerService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, *, store: Store, record_date: date, payload: dict, actor: User,
                     overwrite: bool = False, source: str = "manual",
                     requires_approval: bool = False,
                     approved: bool = True) -> tuple[StoreDailyRecord, bool]:
        local_today = datetime.now(ZoneInfo(store.timezone)).date()
        if record_date > local_today:
            raise HTTPException(422, "Future ledger dates are not allowed")
        record = await self.session.scalar(
            select(StoreDailyRecord).where(
                StoreDailyRecord.store_id == store.id, StoreDailyRecord.date == record_date,
            )
        )
        created = record is None
        if record is not None and not overwrite:
            raise HTTPException(409, "Record exists; confirm overwrite")
        before = None if created else record_snapshot(record)
        if created:
            record = StoreDailyRecord(store_id=store.id, date=record_date, created_by=actor.id, updated_by=actor.id)
            self.session.add(record)
        else:
            record.items.clear()
            record.updated_by = actor.id
        category_ids = {item["category_id"] for item in payload["items"]}
        categories = (await self.session.scalars(
            select(IncomeCategory).where(
                IncomeCategory.store_id == store.id, IncomeCategory.id.in_(category_ids),
            )
        )).all()
        by_id = {category.id: category for category in categories}
        if set(by_id) != category_ids:
            raise HTTPException(422, "Income category does not belong to this store")
        previous_category_ids = set() if created else {item["category_id"] for item in before["items"]}
        if any(not category.is_active and category.id not in previous_category_ids for category in categories):
            raise HTTPException(422, "Inactive categories may only be retained on historical records")
        record.is_open = payload["is_open"]
        record.wash_count = payload.get("wash_count")
        record.weather = payload.get("weather")
        record.weather_edited = payload.get("weather_edited", False)
        for field in (
            "weather_auto", "weather_code", "temperature_max", "temperature_min", "precipitation",
        ):
            if field in payload:
                setattr(record, field, payload[field])
        if not record.weather_edited and not record.weather and record.weather_auto:
            record.weather = record.weather_auto
        record.activity = payload.get("activity")
        record.items = [DailyIncomeItem(category_id=item["category_id"], amount=Decimal(item["amount"])) for item in payload["items"]]
        record.daily_revenue = sum(
            (item.amount for item in record.items if by_id[item.category_id].include_in_total),
            start=Decimal("0.00"),
        )
        await self.session.flush()
        after = record_snapshot(record)
        self.session.add(make_ledger_audit(
            record=record, operation_type="create" if created else "update", source=source,
            user_id=actor.id, before=before, after=after,
            requires_approval=requires_approval, approved=approved,
        ))
        await self.session.commit()
        return record, created
```

- [ ] **Step 4: Add validated routes, delete behavior, and run all ledger tests**

```python
# backend/app/api/routes/ledger.py
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.api.deps import Session, StoreAccess, require_store_access
from app.services.ledger import LedgerService

router = APIRouter(prefix="/ledger", tags=["ledger"])


class IncomeItemBody(BaseModel):
    category_id: int
    amount: Decimal = Field(ge=0)


class LedgerBody(BaseModel):
    is_open: str
    wash_count: int | None = Field(default=None, ge=0)
    weather: str | None = None
    weather_edited: bool = False
    activity: str | None = Field(default=None, max_length=2000)
    items: list[IncomeItemBody]


@router.put("/{store_id}/{record_date}")
async def put_record(store_id: int, record_date: date, body: LedgerBody, session: Session,
                     overwrite: bool = False,
                     access: StoreAccess = Depends(require_store_access)) -> Response:
    record, created = await LedgerService(session).upsert(
        store=access.store, record_date=record_date,
        payload=body.model_dump(mode="json"), actor=access.user, overwrite=overwrite,
    )
    payload = {"id": record.id, "date": record.date.isoformat(), "daily_revenue": str(record.daily_revenue)}
    return Response(content=__import__("json").dumps(payload), media_type="application/json", status_code=201 if created else 200)
```

Add `GET /{store_id}?date=`, `GET /{store_id}/recent?days=7`, and `DELETE /{store_id}/{date}`. Delete must snapshot before deletion, add a `delete` audit entry, delete the record in the same transaction, and return 204. For `休息`, normalize every item to `0.00` and `wash_count` to `0`; for `天气停业`, retain submitted values.

Run: `cd backend && pytest tests/services/test_ledger.py tests/api/test_ledger.py -q`

Expected: revenue, overwrite confirmation, rest-day normalization, future-date, store isolation, delete snapshot, and audit tests pass.

- [ ] **Step 5: Commit the ledger write model**

```bash
git add backend/app/schemas/ledger.py backend/app/services/audit.py backend/app/services/ledger.py backend/app/api/routes/ledger.py backend/app/api/router.py backend/tests
git commit -m "feat: add audited daily ledger writes"
```

### Task 6: Add database search, rollback, history, and Excel export

**Files:**
- Create: `backend/app/schemas/database.py`
- Create: `backend/app/services/rollback.py`
- Create: `backend/app/services/export.py`
- Create: `backend/app/api/routes/database.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/services/test_rollback.py`
- Create: `backend/tests/api/test_database.py`

**Interfaces:**
- Consumes: canonical audit snapshots and `require_store_access`.
- Produces: filtered record pages with dynamic category columns, interval totals, audit history, idempotency-protected rollback, and `.xlsx` bytes matching the active filters.

- [ ] **Step 1: Write failing rollback and export tests**

```python
# backend/tests/services/test_rollback.py
async def test_rollback_update_restores_before_snapshot(rollback_service, updated_audit) -> None:
    restored = await rollback_service.rollback(updated_audit.id, actor_id=updated_audit.operator_user_id)
    assert restored.daily_revenue == updated_audit.before_json["daily_revenue"]
    assert rollback_service.latest_audit.operation_type == "rollback"
    assert rollback_service.latest_audit.before_json == updated_audit.after_json
    assert rollback_service.latest_audit.after_json["daily_revenue"] == updated_audit.before_json["daily_revenue"]
    assert [
        (item["category_id"], item["amount"])
        for item in rollback_service.latest_audit.after_json["items"]
    ] == [
        (item["category_id"], item["amount"])
        for item in updated_audit.before_json["items"]
    ]


async def test_rollback_delete_recreates_record(rollback_service, deleted_audit) -> None:
    restored = await rollback_service.rollback(deleted_audit.id, actor_id=deleted_audit.operator_user_id)
    assert restored.date.isoformat() == deleted_audit.before_json["date"]


async def test_same_audit_cannot_be_rolled_back_twice(rollback_service, updated_audit) -> None:
    await rollback_service.rollback(updated_audit.id, actor_id=updated_audit.operator_user_id)
    with pytest.raises(HTTPException) as error:
        await rollback_service.rollback(updated_audit.id, actor_id=updated_audit.operator_user_id)
    assert error.value.status_code == 409


async def test_rollback_refuses_to_overwrite_a_later_change(rollback_service, updated_audit, later_edit) -> None:
    with pytest.raises(HTTPException) as error:
        await rollback_service.rollback(updated_audit.id, actor_id=updated_audit.operator_user_id)
    assert error.value.status_code == 409
    assert error.value.detail == "Record changed after this audit entry"
```

```python
# backend/tests/api/test_database.py
async def test_export_uses_filtered_rows_and_dynamic_columns(auth_client, assigned_store, seeded_records) -> None:
    response = await auth_client.get(
        f"/api/database/{assigned_store.id}/export.xlsx?start=2026-07-01&end=2026-07-31&status=营业"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    workbook = load_workbook(BytesIO(response.content))
    rows = list(workbook.active.values)
    assert rows[0][:5] == ("日期", "状态", "总收入", "现金", "刷卡")
    assert all(row[1] == "营业" for row in rows[1:])
```

- [ ] **Step 2: Run the focused tests and verify missing rollback/export failures**

Run: `cd backend && pytest tests/services/test_rollback.py tests/api/test_database.py -q`

Expected: FAIL because rollback and database endpoints are missing.

- [ ] **Step 3: Implement snapshot restoration and rollback-chain protection**

```python
# backend/app/services/rollback.py
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.ledger import DailyIncomeItem, StoreDailyRecord
from app.services.audit import make_ledger_audit, record_snapshot


class RollbackService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def rollback(self, audit_id: int, actor_id: int) -> StoreDailyRecord | None:
        audit = await self.session.get(AuditLog, audit_id)
        if audit is None or audit.operation_domain != "ledger":
            raise HTTPException(404, "Audit entry not found")
        already = await self.session.scalar(select(AuditLog.id).where(
            AuditLog.operation_type == "rollback",
            AuditLog.description == f"Rollback audit {audit_id}",
        ))
        if already is not None:
            raise HTTPException(409, "Audit entry already rolled back")
        current = await self.session.scalar(select(StoreDailyRecord).where(
            StoreDailyRecord.store_id == audit.store_id,
            StoreDailyRecord.date == audit.record_date,
        ))
        current_snapshot = None if current is None else record_snapshot(current)
        if current_snapshot != audit.after_json:
            raise HTTPException(409, "Record changed after this audit entry")
        target = audit.before_json
        if target is None:
            if current is not None:
                await self.session.delete(current)
            restored = None
        else:
            restored = current or StoreDailyRecord(store_id=audit.store_id, date=date.fromisoformat(target["date"]))
            if current is None:
                self.session.add(restored)
            for name in (
                "wash_count", "is_open", "weather", "weather_auto", "weather_code", "activity",
                "weather_edited", "scanned",
            ):
                setattr(restored, name, target[name])
            for name in ("daily_revenue", "temperature_max", "temperature_min", "precipitation"):
                value = target[name]
                setattr(restored, name, None if value is None else Decimal(value))
            restored.created_by = target.get("created_by", actor_id)
            restored.updated_by = actor_id
            restored.items = [DailyIncomeItem(category_id=i["category_id"], amount=Decimal(i["amount"])) for i in target["items"]]
            await self.session.flush()
        restored_snapshot = None if restored is None else record_snapshot(restored)
        rollback_audit = AuditLog(
            operation_domain="ledger", store_id=audit.store_id,
            record_id=None if restored is None else restored.id, record_date=audit.record_date,
            operation_type="rollback", operation_source="manual", operator_user_id=actor_id,
            before_json=current_snapshot, after_json=restored_snapshot,
            description=f"Rollback audit {audit_id}", requires_approval=False, approved=True,
        )
        self.session.add(rollback_audit)
        await self.session.commit()
        return restored
```

- [ ] **Step 4: Implement filters, summaries, history, and workbook generation**

```python
# backend/app/services/export.py
from io import BytesIO

from openpyxl import Workbook


def build_ledger_workbook(records: list[dict], categories: list[dict]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "经营记录"
    headers = ["日期", "状态", "总收入", *[c["name"] for c in categories],
               "洗车", "天气", "活动", "记录人", "最后修改人"]
    sheet.append(headers)
    for record in records:
        amounts = {item["category_id"]: item["amount"] for item in record["items"]}
        sheet.append([
            record["date"], record["is_open"], float(record["daily_revenue"]),
            *[float(amounts.get(c["id"], 0)) for c in categories],
            record["wash_count"], record["weather"], record["activity"],
            record["created_by_name"], record["updated_by_name"],
        ])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
```

In `database.py`, implement one shared `build_record_query(store_id, filters)` used by both JSON and export routes. Support `start`, `end`, `status`, `weather`, case-insensitive `activity_query` substring, and `missing_wash_count`; return `items`, dynamic category descriptors, `sum_daily_revenue`, and pagination. History is ordered newest first and never exposes another store. Rollback requires `require_store_access` and verifies `audit.store_id == store_id` before calling the service.

Run: `cd backend && pytest tests/services/test_rollback.py tests/api/test_database.py -q`

Expected: update/delete/create rollback, later-change conflict, double-rollback protection, store isolation, all filters, interval summary, history, and Excel column tests pass.

- [ ] **Step 5: Commit database management and export**

```bash
git add backend/app/schemas/database.py backend/app/services/rollback.py backend/app/services/export.py backend/app/api/routes/database.py backend/app/api/router.py backend/tests
git commit -m "feat: add ledger search rollback and export"
```

### Task 7: Add non-blocking Open-Meteo lookup and basic briefing generation

**Files:**
- Create: `backend/app/services/weather.py`
- Create: `backend/app/services/briefing.py`
- Create: `backend/app/services/scheduler.py`
- Create: `backend/app/api/routes/dashboard.py`
- Modify: `backend/app/api/routes/ledger.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/services/test_weather.py`
- Create: `backend/tests/services/test_briefing.py`
- Create: `backend/tests/api/test_dashboard.py`

**Interfaces:**
- Consumes: store coordinates/time zone, ledger records, and `httpx.AsyncClient`.
- Produces: `WeatherService.get_daily(store, date) -> WeatherResult | None`, `BriefingService.regenerate(store_id, card_types)`, cached `GET /api/dashboard/{store_id}`, and rate-limited manual refresh.

- [ ] **Step 1: Write failing weather resilience and briefing text tests**

```python
# backend/tests/services/test_weather.py
async def test_forecast_maps_open_meteo_day(weather_service, respx_mock, store) -> None:
    respx_mock.get("https://api.open-meteo.com/v1/forecast").mock(return_value=Response(200, json={
        "daily": {"time": ["2026-07-13"], "weather_code": [1],
                  "temperature_2m_max": [31.2], "temperature_2m_min": [20.1],
                  "precipitation_sum": [0.0]},
    }))
    result = await weather_service.get_daily(store, date(2026, 7, 13))
    assert result.weather == "晴"
    assert result.weather_code == 1


async def test_weather_failure_returns_none(weather_service, respx_mock, store) -> None:
    respx_mock.get("https://api.open-meteo.com/v1/forecast").mock(side_effect=httpx.TimeoutException("slow"))
    assert await weather_service.get_daily(store, date(2026, 7, 13)) is None
```

```python
# backend/tests/services/test_briefing.py
async def test_yesterday_card_mentions_missing_record(briefing_service, store) -> None:
    cards = await briefing_service.regenerate(store.id, ["yesterday"], local_date=date(2026, 7, 13))
    assert cards[0].content == "昨天还没有经营记录，可以在记账页补录。"
```

- [ ] **Step 2: Run tests and verify weather/briefing modules are absent**

Run: `cd backend && pytest tests/services/test_weather.py tests/services/test_briefing.py -q`

Expected: FAIL during import of weather and briefing services.

- [ ] **Step 3: Implement forecast/archive selection and stable weather mapping**

```python
# backend/app/services/weather.py
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from app.models.identity import Store


@dataclass(frozen=True)
class WeatherResult:
    weather: str
    weather_code: int
    temperature_max: float
    temperature_min: float
    precipitation: float


def weather_label(code: int) -> str:
    if code == 0:
        return "晴"
    if code in {1, 2, 3}:
        return "多云"
    if code in {45, 48}:
        return "雾"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "雨"
    if code in {71, 73, 75, 77, 85, 86}:
        return "雪"
    if code in {95, 96, 99}:
        return "雷雨"
    return "未知"


class WeatherProvider(Protocol):
    async def get_daily(self, store: Store, target: date) -> WeatherResult | None: ...


class OpenMeteoProvider:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def get_daily(self, store: Store, target: date) -> WeatherResult | None:
        today = datetime.now(ZoneInfo(store.timezone)).date()
        base = "https://api.open-meteo.com/v1/forecast" if target >= today else "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": float(store.latitude), "longitude": float(store.longitude),
            "start_date": target.isoformat(), "end_date": target.isoformat(),
            "timezone": store.timezone,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
        }
        try:
            response = await self.client.get(base, params=params, timeout=8)
            response.raise_for_status()
            daily = response.json()["daily"]
            code = int(daily["weather_code"][0])
            return WeatherResult(weather_label(code), code, daily["temperature_2m_max"][0],
                                 daily["temperature_2m_min"][0], daily["precipitation_sum"][0])
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return None


class WeatherService:
    def __init__(self, primary: WeatherProvider, fallback: WeatherProvider | None = None):
        self.primary, self.fallback = primary, fallback

    async def get_daily(self, store: Store, target: date) -> WeatherResult | None:
        result = await self.primary.get_daily(store, target)
        if result is not None or self.fallback is None:
            return result
        return await self.fallback.get_daily(store, target)
```

- [ ] **Step 4: Add geocoding, deterministic cards, and non-blocking lookups**

Add `OpenMeteoProvider.geocode(query)` against `https://geocoding-api.open-meteo.com/v1/search` and expose it only as admin `GET /admin/stores/geocode?query=`; return normalized name, latitude, longitude, country, and timezone candidates. Keep the `WeatherProvider` protocol as the reserved integration point for 和风天气 without enabling it until credentials/configuration exist. On ledger save, the route performs a bounded weather lookup and, when successful, adds trusted `weather_auto`, `weather_code`, `temperature_max`, `temperature_min`, and `precipitation` values to the service payload; a timeout passes no automatic fields and the ledger transaction still proceeds. Implement `BriefingService` with these exact copy rules: missing yesterday record → `昨天还没有经营记录，可以在记账页补录。`; existing yesterday → include total revenue, the leading included income categories, status, weather when present, wash count when non-null, and activity when non-empty; today → show weather or `天气暂时不可用`, recording status, and today's revenue when already recorded; tomorrow → show weather or `天气暂时不可用` plus the localized weekday. Upsert each `DailyBriefing` by `(store_id, card_type)`. Manual refresh has a five-minute per-user/store limit and returns 429 inside that window. Ledger weather lookup returns 200 with `null` fields on failure and ledger saving remains independent.

Run: `cd backend && pytest tests/services/test_weather.py tests/services/test_briefing.py tests/api/test_dashboard.py tests/api/test_ledger.py -q`

Expected: weather mapping, timeout fallback, manual weather preservation, briefing copy, cached reads, refresh limit, and non-blocking ledger tests pass.

- [ ] **Step 5: Commit weather and briefing services**

```bash
git add backend/app/services/weather.py backend/app/services/briefing.py backend/app/services/scheduler.py backend/app/api/routes/dashboard.py backend/app/api/routes/ledger.py backend/app/main.py backend/tests
git commit -m "feat: add resilient weather and dashboard briefings"
```

### Task 8: Implement store-scoped analytics APIs

**Files:**
- Create: `backend/app/schemas/charts.py`
- Create: `backend/app/services/analytics.py`
- Create: `backend/app/api/routes/charts.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/services/test_analytics.py`
- Create: `backend/tests/api/test_charts.py`

**Interfaces:**
- Consumes: filtered ledger records and income items for one authorized store.
- Produces: a JSON-ready dictionary containing KPIs, daily revenue, category composition, monthly trend, weather groups, weekday groups, and conditional wash metrics.

- [ ] **Step 1: Write failing aggregate and wash-mode tests**

```python
# backend/tests/services/test_analytics.py
async def test_analytics_returns_expected_groups(analytics_service, july_records) -> None:
    result = await analytics_service.calculate(
        store_id=july_records.store_id, start=date(2026, 7, 1), end=date(2026, 7, 31),
        category_ids=[july_records.cash_id, july_records.card_id],
    )
    assert result["kpis"]["total_revenue"] == "350.00"
    assert result["kpis"]["record_days"] == 2
    assert result["kpis"]["open_days"] == 1
    assert result["daily"][0]["date"] == "2026-07-12"
    assert {item["weather"] for item in result["weather"]} == {"晴", "雨"}


async def test_wash_metrics_are_absent_without_recorded_counts(analytics_service, records_without_wash) -> None:
    result = await analytics_service.calculate_for_fixture(records_without_wash)
    assert result["kpis"]["total_wash_count"] is None
    assert result["kpis"]["average_ticket"] is None
```

- [ ] **Step 2: Run analytics tests and verify missing service failure**

Run: `cd backend && pytest tests/services/test_analytics.py tests/api/test_charts.py -q`

Expected: FAIL because analytics service and route do not exist.

- [ ] **Step 3: Implement one-query record loading and pure aggregation**

```python
# backend/app/services/analytics.py
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ledger import StoreDailyRecord


class AnalyticsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def calculate(self, *, store_id: int, start: date, end: date,
                        category_ids: list[int]) -> dict:
        records = (await self.session.scalars(
            select(StoreDailyRecord)
            .options(selectinload(StoreDailyRecord.items))
            .where(StoreDailyRecord.store_id == store_id,
                   StoreDailyRecord.date.between(start, end))
            .order_by(StoreDailyRecord.date)
        )).all()
        total = sum((r.daily_revenue for r in records), Decimal("0.00"))
        recorded_wash = [r.wash_count for r in records if r.wash_count is not None]
        category_totals: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
        weather_totals: dict[str, list[Decimal]] = defaultdict(list)
        weekday_totals: dict[int, list[Decimal]] = defaultdict(list)
        monthly_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        for record in records:
            for item in record.items:
                if item.category_id in category_ids:
                    category_totals[item.category_id] += item.amount
            weather_totals[record.weather or "未记录"].append(record.daily_revenue)
            weekday_totals[record.date.weekday()].append(record.daily_revenue)
            monthly_totals[record.date.strftime("%Y-%m")] += record.daily_revenue
        total_wash = sum(recorded_wash) if recorded_wash else None
        return {
            "kpis": {
                "total_revenue": str(total), "record_days": len(records),
                "open_days": sum(r.is_open == "营业" for r in records),
                "primary_categories": [
                    {"category_id": key, "amount": str(value)}
                    for key, value in sorted(category_totals.items(), key=lambda pair: pair[1], reverse=True)[:3]
                ],
                "total_wash_count": total_wash,
                "average_ticket": None if not total_wash else str(total / total_wash),
            },
            "daily": [{"date": r.date.isoformat(), "revenue": str(r.daily_revenue)} for r in records],
            "categories": [{"category_id": key, "amount": str(value)} for key, value in sorted(category_totals.items())],
            "monthly": [{"month": key, "revenue": str(value)} for key, value in sorted(monthly_totals.items())],
            "weather": [{"weather": key, "average_revenue": str(sum(values) / len(values))} for key, values in sorted(weather_totals.items())],
            "weekday": [{"weekday": key, "average_revenue": str(sum(values) / len(values))} for key, values in sorted(weekday_totals.items())],
        }
```

- [ ] **Step 4: Add authorized query parsing and verify endpoint contracts**

Implement `GET /api/charts/{store_id}?start=&end=&category_id=`. Default category selection contains every `include_in_total=true` category for the store; repeated `category_id` values select explicit composition items. Validate `start <= end`, use `require_store_access`, and never accept multiple stores. Return Decimal values as JSON strings so the TypeScript client can display without binary rounding surprises.

Run: `cd backend && pytest tests/services/test_analytics.py tests/api/test_charts.py -q`

Expected: KPI, daily, category, monthly, weather, weekday, optional wash metrics, date validation, and store-isolation tests pass.

- [ ] **Step 5: Commit analytics APIs**

```bash
git add backend/app/schemas/charts.py backend/app/services/analytics.py backend/app/api/routes/charts.py backend/app/api/router.py backend/tests
git commit -m "feat: add store-scoped business analytics"
```

### Task 9: Build authenticated navigation, store selection, and administration UI

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/auth/AuthProvider.tsx`
- Create: `frontend/src/stores/StoreProvider.tsx`
- Create: `frontend/src/layouts/AppShell.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/pages/AdminPage.tsx`
- Create: `frontend/src/router.tsx`
- Modify: `frontend/src/main.tsx`
- Create: `frontend/src/auth/AuthProvider.test.tsx`
- Create: `frontend/src/pages/AdminPage.test.tsx`

**Interfaces:**
- Consumes: auth, accessible-store, and admin APIs.
- Produces: `api<T>(path, init)`, `useAuth()`, `useStore()`, protected routes, admin-only route, desktop top navigation, and mobile bottom tabs.

- [ ] **Step 1: Write failing auth redirect and single-store selection tests**

```tsx
// frontend/src/auth/AuthProvider.test.tsx
it("redirects unauthenticated visitors to login", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ detail: "Authentication required" }, { status: 401 })));
  renderTestRouter("/ledger");
  expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
});

it("automatically selects the only accessible store", async () => {
  server.use(http.get("/api/stores/accessible", () => HttpResponse.json([
    { id: 7, name: "Lavaggio Roma", timezone: "Europe/Rome" },
  ])));
  renderWithProviders(<StoreProbe />);
  expect(await screen.findByText("selected:7")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run frontend tests and verify missing providers**

Run: `cd frontend && npm test -- AuthProvider AdminPage`

Expected: FAIL because provider, router, and admin page modules do not exist.

- [ ] **Step 3: Implement the credentialed API client and providers**

```ts
// frontend/src/api/client.ts
export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(detail); }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, body.detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
```

```tsx
// frontend/src/stores/StoreProvider.tsx
type Store = { id: number; name: string; timezone: string };
type StoreContextValue = { stores: Store[]; selected: Store | null; select(id: number): void };
const StoreContext = createContext<StoreContextValue | null>(null);

export function StoreProvider({ children }: PropsWithChildren) {
  const { data: stores = [] } = useQuery({ queryKey: ["stores"], queryFn: () => api<Store[]>("/stores/accessible") });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  useEffect(() => {
    if (stores.length === 1) setSelectedId(stores[0].id);
    if (selectedId !== null && !stores.some((store) => store.id === selectedId)) setSelectedId(null);
  }, [stores, selectedId]);
  return <StoreContext.Provider value={{
    stores, selected: stores.find((store) => store.id === selectedId) ?? null,
    select: setSelectedId,
  }}>{children}</StoreContext.Provider>;
}
```

- [ ] **Step 4: Implement routes/navigation/admin forms and verify behavior**

Create routes for `/login`, `/`, `/ledger`, `/database`, `/charts`, and `/admin`. `AppShell` uses top navigation at `min-width: 768px` and fixed bottom tabs below it. `AdminPage` renders user, store, membership, category, alert, and task-log tabs; mutation success invalidates the exact React Query list key. Hide the admin route and link for role `user`, while the backend remains the authority.

Run: `cd frontend && npm test -- AuthProvider AdminPage && npm run build`

Expected: auth redirect, remembered login request, logout, store auto-selection, admin visibility, configuration mutation, responsive navigation, and production build pass.

- [ ] **Step 5: Commit application shell and admin UI**

```bash
git add frontend/src
git commit -m "feat: add authenticated shell and admin interface"
```

### Task 10: Build ledger, database, dashboard, and charts UI

**Files:**
- Create: `frontend/src/components/StorePicker.tsx`
- Create: `frontend/src/components/BriefingCards.tsx`
- Create: `frontend/src/components/LedgerForm.tsx`
- Create: `frontend/src/components/RecordTable.tsx`
- Create: `frontend/src/components/ChartPanel.tsx`
- Create: `frontend/src/pages/HomePage.tsx`
- Create: `frontend/src/pages/LedgerPage.tsx`
- Create: `frontend/src/pages/DatabasePage.tsx`
- Create: `frontend/src/pages/ChartsPage.tsx`
- Create: `frontend/src/pages/LedgerPage.test.tsx`
- Create: `frontend/src/pages/DatabasePage.test.tsx`
- Create: `frontend/src/pages/ChartsPage.test.tsx`
- Create: `frontend/tests/responsive.spec.ts`

**Interfaces:**
- Consumes: every Phase 1 user-facing API.
- Produces: fast manual ledger form, overwrite confirmation, recent-seven-day links, filtered database with edit/delete/history/rollback/export, three-card home, and six responsive chart views.

- [ ] **Step 1: Write failing user-journey component tests**

```tsx
// frontend/src/pages/LedgerPage.test.tsx
it("calculates total from included categories and asks before overwrite", async () => {
  renderLedger({ categories: [
    { id: 1, name: "现金", include_in_total: true },
    { id: 2, name: "刷卡", include_in_total: true },
    { id: 3, name: "暗钱", include_in_total: false },
  ]});
  await user.type(await screen.findByLabelText("现金"), "200");
  await user.type(screen.getByLabelText("刷卡"), "150");
  await user.type(screen.getByLabelText("暗钱"), "80");
  expect(screen.getByText("€350.00")).toBeInTheDocument();
  server.use(http.put("/api/ledger/1/2026-07-13", () => HttpResponse.json(
    { detail: "Record exists; confirm overwrite" }, { status: 409 },
  )));
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByRole("dialog", { name: "覆盖已有记录？" })).toBeInTheDocument();
});
```

```tsx
// frontend/src/pages/ChartsPage.test.tsx
it("hides wash metrics when the API returns null", async () => {
  renderCharts({ kpis: { total_revenue: "350.00", record_days: 2, open_days: 1,
    total_wash_count: null, average_ticket: null }, daily: [], categories: [], monthly: [], weather: [], weekday: [] });
  expect(await screen.findByText("总收入")).toBeInTheDocument();
  expect(screen.queryByText("平均客单价")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run focused UI tests and verify missing pages/components**

Run: `cd frontend && npm test -- LedgerPage DatabasePage ChartsPage`

Expected: FAIL because the Phase 1 user pages are missing.

- [ ] **Step 3: Implement ledger and home flows**

```tsx
// frontend/src/components/LedgerForm.tsx (calculation and status normalization)
const includedIds = new Set(categories.filter((item) => item.include_in_total).map((item) => item.id));
const total = values.items.reduce(
  (sum, item) => includedIds.has(item.category_id) ? sum + Number(item.amount || 0) : sum,
  0,
);

function applyStatus(status: "营业" | "休息" | "天气停业") {
  setValue("is_open", status);
  if (status === "休息") {
    setValue("wash_count", 0);
    categories.forEach((category, index) => setValue(`items.${index}.amount`, "0"));
  }
}
```

`LedgerPage` selects today in the store time zone, disables future dates, loads active categories, requests weather without blocking the form, and marks `weather_edited=true` after a user change. On 409 it opens an accessible confirmation dialog; confirmation repeats the same request with `?overwrite=true`. After save, invalidate ledger, recent records, database, charts, and dashboard queries. `HomePage` reads cached cards immediately and exposes a refresh button that displays the API's 429 message.

- [ ] **Step 4: Implement database/charts views and verify mobile behavior**

`DatabasePage` supports exact quick ranges (this month, last month, 7 days, 30 days), explicit date range, status, weather, activity-text search, and missing-wash filters. The result table derives category columns from the response, uses a dialog/drawer for edits, requires confirmation for delete/rollback, and downloads the export URL with identical query parameters. `ChartsPage` renders Recharts bar, pie, line, weather bar, and weekday bar components; category checkboxes default to included categories with no select-all control; the three leading category amounts render as KPI details; wash KPI cards render only for non-null API values.

Run: `cd frontend && npm test && npx playwright test frontend/tests/responsive.spec.ts && npm run build`

Expected: all unit tests pass; Playwright verifies a 390px ledger form without horizontal overflow, a horizontally scrollable database table, desktop top navigation, mobile bottom tabs, and chart controls; production build passes.

- [ ] **Step 5: Commit the complete Phase 1 user interface**

```bash
git add frontend/src frontend/tests
git commit -m "feat: add ledger database dashboard and charts UI"
```

### Task 11: Package deployment, seed the first administrator, and verify the release

**Files:**
- Create: `.env.example`
- Create: `backend/Dockerfile`
- Create: `backend/app/scripts/create_admin.py`
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Create: `compose.yaml`
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`
- Create: `backend/tests/test_deployment_config.py`

**Interfaces:**
- Consumes: built backend/frontend, server-host MySQL URL, and first-admin environment values.
- Produces: two-container deployment, idempotent admin bootstrap command, `/api` reverse proxy, and CI release gate.

- [ ] **Step 1: Write a failing deployment-boundary test**

```python
# backend/tests/test_deployment_config.py
from pathlib import Path

import yaml


def test_compose_contains_only_api_and_web() -> None:
    compose = yaml.safe_load(Path("../compose.yaml").read_text())
    assert set(compose["services"]) == {"autolava-api", "autolava-web"}
    assert "AUTOLAVA_DATABASE_URL" in compose["services"]["autolava-api"]["environment"]
```

- [ ] **Step 2: Run the deployment test and verify compose is missing**

Run: `cd backend && pytest tests/test_deployment_config.py -q`

Expected: FAIL with `FileNotFoundError` for `compose.yaml`.

- [ ] **Step 3: Add production images and host-MySQL compose configuration**

```yaml
# compose.yaml
services:
  autolava-api:
    build: ./backend
    restart: unless-stopped
    environment:
      AUTOLAVA_ENVIRONMENT: production
      AUTOLAVA_DATABASE_URL: ${AUTOLAVA_DATABASE_URL}
      AUTOLAVA_JWT_SECRET: ${AUTOLAVA_JWT_SECRET}
      AUTOLAVA_COOKIE_SECURE: "true"
    extra_hosts:
      - "host.docker.internal:host-gateway"
  autolava-web:
    build: ./frontend
    restart: unless-stopped
    ports:
      - "80:80"
    depends_on:
      - autolava-api
```

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN pip install --no-cache-dir .
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
```

```nginx
# frontend/nginx.conf
server {
  listen 80;
  root /usr/share/nginx/html;
  index index.html;
  location /api/ { proxy_pass http://autolava-api:8000/api/; }
  location /health { proxy_pass http://autolava-api:8000/health; }
  location / { try_files $uri /index.html; }
}
```

- [ ] **Step 4: Add CI, bootstrap documentation, and run the full release gate**

The admin script accepts `AUTOLAVA_BOOTSTRAP_USERNAME` and `AUTOLAVA_BOOTSTRAP_PASSWORD`, creates an admin only when the username does not exist, hashes the password with `hash_password`, and exits successfully without changing an existing account. CI starts a MySQL service for backend migrations/tests, runs Ruff and pytest with coverage, runs `npm ci`, Vitest, Vite build, and Playwright, then runs `docker compose config` and `docker compose build`.

Run locally:

```bash
cd backend && ruff check . && pytest --cov=app --cov-report=term-missing
cd ../frontend && npm test && npm run build && npx playwright test
cd .. && docker compose config && docker compose build
```

Expected: no lint errors; all backend, frontend, and browser tests pass; both images build; rendered compose lists exactly `autolava-api` and `autolava-web`.

- [ ] **Step 5: Commit the Phase 1 release package**

```bash
git add .env.example .github compose.yaml backend frontend README.md
git commit -m "build: package phase one deployment and CI"
```

## Phase 1 acceptance checklist

- A disabled or unauthenticated user cannot access business data.
- A regular user sees only assigned active stores; an administrator sees all active stores.
- The administrator can create/disable users and stores, replace memberships, and configure ordered income categories.
- Ledger total excludes categories marked `include_in_total=false`, and overwrite requires confirmation.
- Ledger save succeeds when Open-Meteo times out; user-edited final weather survives later automatic refresh.
- Database filters, summary, history, delete, rollback, and Excel export operate on the same store-scoped dataset.
- Charts never compare stores and hide wash metrics when no wash count was recorded.
- Home reads three stored cards without waiting for weather or generation.
- Mobile ledger is usable without horizontal scrolling; the database table scrolls horizontally.
- Deployment compose contains only API and Web services and persists SQLite under `/data`.
