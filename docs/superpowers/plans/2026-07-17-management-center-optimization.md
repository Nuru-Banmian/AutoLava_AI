# Management Center Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the AutoLava management center as responsive store and user workspaces while enforcing a configurable final-administrator hierarchy on the server.

**Architecture:** Add a small backend owner-identity service and enforce owner/administrator rules at every user mutation boundary. On the frontend, replace the four independent admin panels with two master-detail workspaces plus the existing status panel; reuse the global unsaved-changes coordinator so object and tab switches cannot discard drafts silently.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Pydantic Settings, pytest, React, TypeScript, TanStack Query, React Router, Radix UI, Tailwind CSS, Vitest/Testing Library/MSW, Playwright.

## Global Constraints

- The final administrator is identified only by `AUTOLAVA_BOOTSTRAP_USERNAME`; never hardcode `Nuru_Banmian` in application code.
- Backend authorization is authoritative. Hidden or disabled frontend controls do not replace API checks.
- The final administrator is hidden only from user management; audit, database, and system-log usernames remain truthful.
- Non-owner administrators may manage ordinary users but may not create, promote, edit, reset, deactivate, demote, or delete any administrator.
- The owner may manage other administrators but may not mutate the configured owner through admin user APIs.
- Keep `GET/PUT /api/admin/stores/{store_id}/members` available, but remove all management-center calls to them.
- Keep database history/rollback behavior and system-status data semantics unchanged.
- Admin tabs are exactly `门店与收入`, `用户与权限`, `系统状态`, in that order; `门店与收入` is the default.
- Store details and income configuration save independently. Income configuration retains versioned publish behavior.
- On desktop, store details use one compact row: name, location summary, `修改位置`, and `保存`; narrow screens may wrap naturally.
- The primary button text in both the store-details card and income-items card is exactly `保存`; income `保存` still publishes a version.
- User deletion is the rightmost action in the editor footer; do not render a separate danger card or persistent deletion guidance. Keep confirmation and show deactivation guidance only after a history-reference rejection.
- Never auto-save or silently discard a user, store, or income draft.
- Backend database tests require `AUTOLAVA_DATABASE_URL` to point to the dedicated MySQL database named exactly `autolava_test`.
- Keep all implementation commits on `codex/management-center-optimization`. Before final integration, merge the latest `feature/phase-1-foundation` into this branch, resolve overlapping edits deliberately, rerun full verification, then use a normal merge back; never force-reset or copy this branch over Phase 1.

## File Structure

### Backend

- Create `backend/app/services/owner.py`: normalize the configured owner username, compare a `User` to it, and build the authenticated-user payload.
- Modify `backend/app/core/config.py`: expose `bootstrap_username` through `Settings`.
- Modify `backend/app/schemas/admin.py`: accept `store_ids` when an ordinary user is created.
- Modify `backend/app/api/routes/auth.py`: return `is_owner` from login and session reads.
- Modify `backend/app/api/routes/admin.py`: filter the owner from user lists and enforce target/role guards on create, patch, and delete.
- Modify `backend/tests/api/test_auth.py`: verify owner identity serialization.
- Modify `backend/tests/api/test_admin.py`: verify the full owner/administrator permission matrix and audit atomicity.

### Frontend

- Modify `frontend/src/api/types.ts`: add an `AuthenticatedUser` subtype with `is_owner` without changing `AdminUser`.
- Modify `frontend/src/auth/AuthProvider.tsx`: use `AuthenticatedUser` for session and login state.
- Create `frontend/src/admin/UserEditor.tsx`: one create/edit form for role, status, memberships, the single password field, footer save, and right-aligned delete.
- Rewrite `frontend/src/admin/UsersPanel.tsx`: user master-detail selection, read-only administrator view, mutations, deletion, and dirty-transition coordination.
- Rewrite `frontend/src/admin/UsersPanel.test.tsx`: new workspace, hierarchy, removed duplicate UI, errors, and unsaved switching.
- Create `frontend/src/admin/StoreDetailsCard.tsx`: compact controlled create/edit row plus the existing store lifecycle actions.
- Create `frontend/src/admin/StoreWorkspace.tsx`: shared store selection, responsive master-detail layout, and aggregate dirty state.
- Modify `frontend/src/admin/IncomeItemsPanel.tsx`: accept one store ID, remove its store query/selector, and report dirty state upward.
- Modify `frontend/src/admin/IncomeItemsPanel.test.tsx`: controlled-store contract and dirty notifications.
- Replace `frontend/src/admin/StoreSettingsPanel.test.tsx` with `frontend/src/admin/StoreWorkspace.test.tsx`: merged layout, separate saves, and switch guard.
- Delete `frontend/src/admin/StoreSettingsPanel.tsx` after its behavior is moved into `StoreDetailsCard.tsx` and `StoreWorkspace.tsx`.
- Modify `frontend/src/admin/AdminLayout.tsx`: integrate the three tabs as part of the store-workspace task so every task remains buildable.
- Modify `frontend/src/pages/AdminPage.tsx`: first remove obsolete user props in Task 3, then render the merged store workspace and guard tab changes in Task 4.
- Modify `frontend/src/pages/AdminPage.test.tsx`: repair the user harness in Task 3, then cover tab order, defaults, removed endpoints, and responsive behavior in Task 4.
- Modify `frontend/src/admin/SystemStatusPanel.tsx`: visual-only card hierarchy adjustment.
- Modify `frontend/src/admin/SystemStatusPanel.test.tsx`: assert the new semantic regions while retaining all status truthfulness tests.
- Modify `frontend/src/auth/AuthProvider.test.tsx` and `frontend/src/App.test.tsx`: include and preserve `is_owner` in auth fixtures.
- Modify `frontend/tests/admin-flow.spec.ts`: exercise the merged store workspace and user workspace end to end.

---

### Task 1: Add Configured Owner Identity to Authentication

**Files:**
- Create: `backend/app/services/owner.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/api/routes/auth.py`
- Modify: `backend/tests/api/test_auth.py`

**Interfaces:**
- Consumes: `Settings.bootstrap_username`, `User.username`.
- Produces: `owner_username() -> str`, `is_owner(user: User) -> bool`, `authenticated_user_payload(user: User) -> dict[str, Any]`, and auth JSON with required `is_owner: bool`.

- [ ] **Step 1: Write failing authentication owner tests**

Append focused tests to `backend/tests/api/test_auth.py`:

```python
async def test_login_and_me_report_configured_owner(
    client, user_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "Nuru_Banmian")
    get_settings.cache_clear()
    await user_factory(username="Nuru_Banmian", password="secret123", role="admin")

    login = await client.post("/api/auth/login", json={
        "username": "Nuru_Banmian", "password": "secret123", "remember": False,
    })
    assert login.status_code == 200
    assert login.json() == {
        "id": login.json()["id"],
        "username": "Nuru_Banmian",
        "role": "admin",
        "is_owner": True,
    }
    assert (await client.get("/api/auth/me")).json()["is_owner"] is True


async def test_non_owner_auth_payload_is_explicitly_false(
    client, user_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "Nuru_Banmian")
    get_settings.cache_clear()
    await user_factory(username="secondary-admin", password="secret123", role="admin")

    response = await client.post("/api/auth/login", json={
        "username": "secondary-admin", "password": "secret123", "remember": False,
    })
    assert response.status_code == 200
    assert response.json()["is_owner"] is False
```

- [ ] **Step 2: Run the tests and verify the contract is missing**

Run from `backend` with the dedicated test database configured:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_auth.py::test_login_and_me_report_configured_owner tests/api/test_auth.py::test_non_owner_auth_payload_is_explicitly_false -q
```

Expected: FAIL because login and `/auth/me` do not return `is_owner`.

- [ ] **Step 3: Implement the owner identity service and auth payload**

Add this field to `Settings` in `backend/app/core/config.py`:

```python
bootstrap_username: str = ""
```

Create `backend/app/services/owner.py`:

```python
from typing import Any

from app.core.config import get_settings
from app.models.identity import User


def owner_username() -> str:
    return get_settings().bootstrap_username.strip()


def is_owner(user: User) -> bool:
    configured = owner_username()
    return bool(configured) and user.username == configured


def authenticated_user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_owner": is_owner(user),
    }
```

Import `authenticated_user_payload` in `backend/app/api/routes/auth.py` and replace both duplicated auth dictionaries:

```python
from app.services.owner import authenticated_user_payload

# login
return authenticated_user_payload(user)

# /auth/me
return authenticated_user_payload(user)
```

- [ ] **Step 4: Run owner tests and the complete auth module**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_auth.py -q
```

Expected: PASS with both owner tests and all existing authentication tests green.

- [ ] **Step 5: Lint and commit the owner identity foundation**

```powershell
.\.venv\Scripts\python.exe -m ruff check app/core/config.py app/services/owner.py app/api/routes/auth.py tests/api/test_auth.py
git add backend/app/core/config.py backend/app/services/owner.py backend/app/api/routes/auth.py backend/tests/api/test_auth.py
git commit -m "feat: expose configured owner identity"
```

Expected: Ruff passes and the commit contains only the four listed files.

---

### Task 2: Enforce the Administrator Hierarchy in User APIs

**Files:**
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/app/api/routes/admin.py`
- Modify: `backend/tests/api/test_admin.py`

**Interfaces:**
- Consumes: `is_owner(user: User) -> bool`, `owner_username() -> str` from Task 1.
- Produces: `UserCreate.store_ids: list[int]`; `_require_can_assign_role(actor: User, role: str | None) -> None`, `_require_can_manage_target(actor: User, target: User) -> None`; `GET /admin/users` excludes the owner; create/patch/delete return 403 for forbidden administrator operations.

- [ ] **Step 1: Write the owner filtering and permission-matrix tests**

Import `get_settings` and make the existing `admin_client` fixture represent the configured owner by default:

```python
from app.core.config import get_settings


@pytest.fixture
async def admin_client(client, user_factory, monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "administrator")
    get_settings.cache_clear()
    await user_factory(username="administrator", password="secret", role="admin")
    response = await client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "secret", "remember": False},
    )
    assert response.status_code == 200
    return client
```

Add these tests to `backend/tests/api/test_admin.py`:

```python
async def test_user_list_hides_only_the_configured_owner(
    admin_client, user_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "Nuru_Banmian")
    get_settings.cache_clear()
    await user_factory(username="Nuru_Banmian", password="secret123", role="admin")
    await user_factory(username="visible-admin", password="secret123", role="admin")
    await user_factory(username="visible-user", password="secret123")

    response = await admin_client.get("/api/admin/users")
    assert response.status_code == 200
    assert [item["username"] for item in response.json()] == [
        "administrator", "visible-admin", "visible-user",
    ]


async def test_non_owner_cannot_create_promote_or_mutate_administrators(
    admin_client, user_factory, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "Nuru_Banmian")
    get_settings.cache_clear()
    owner = await user_factory(username="Nuru_Banmian", password="secret123", role="admin")
    other_admin = await user_factory(username="other-admin", password="secret123", role="admin")
    ordinary = await user_factory(username="ordinary", password="secret123")
    actor = await db_session.scalar(select(User).where(User.username == "administrator"))
    assert actor is not None
    audits_before = await db_session.scalar(select(func.count()).select_from(AuditLog))

    assert (await admin_client.post("/api/admin/users", json={
        "username": "forbidden-admin", "password": "secret123", "role": "admin",
    })).status_code == 403
    assert (await admin_client.patch(
        f"/api/admin/users/{ordinary.id}", json={"role": "admin"}
    )).status_code == 403
    for target in (owner, other_admin):
        assert (await admin_client.patch(
            f"/api/admin/users/{target.id}", json={"password": "replacement123"}
        )).status_code == 403
        assert (await admin_client.delete(f"/api/admin/users/{target.id}")).status_code == 403
    assert (await admin_client.patch(
        f"/api/admin/users/{actor.id}", json={"password": "replacement123"}
    )).status_code == 403
    assert await db_session.scalar(select(func.count()).select_from(AuditLog)) == audits_before
    await db_session.refresh(ordinary)
    await db_session.refresh(other_admin)
    assert ordinary.role == "user"
    assert other_admin.is_active is True


async def test_owner_can_manage_other_admin_but_not_itself(
    client, user_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "Nuru_Banmian")
    get_settings.cache_clear()
    owner = await user_factory(username="Nuru_Banmian", password="secret123", role="admin")
    target = await user_factory(username="secondary-admin", password="secret123", role="admin")
    await client.post("/api/auth/login", json={
        "username": owner.username, "password": "secret123", "remember": False,
    })

    demoted = await client.patch(f"/api/admin/users/{target.id}", json={"role": "user"})
    assert demoted.status_code == 200
    assert demoted.json()["role"] == "user"
    created = await client.post("/api/admin/users", json={
        "username": "new-admin", "password": "secret123", "role": "admin",
    })
    assert created.status_code == 201
    assert created.json()["role"] == "admin"
    assert (await client.patch(
        f"/api/admin/users/{owner.id}", json={"password": "replacement123"}
    )).status_code == 403


async def test_create_ordinary_user_assigns_stores_in_the_same_request(
    admin_client, store_factory, db_session: AsyncSession
) -> None:
    first = await store_factory(name="First")
    second = await store_factory(name="Second")

    created = await admin_client.post("/api/admin/users", json={
        "username": "new-operator",
        "password": "secret123",
        "role": "user",
        "store_ids": [second.id, first.id, second.id],
    })
    assert created.status_code == 201
    assert created.json()["store_ids"] == [first.id, second.id]
    assert list(await db_session.scalars(
        select(StoreMember.store_id)
        .where(StoreMember.user_id == created.json()["id"])
        .order_by(StoreMember.store_id)
    )) == [first.id, second.id]
```

Update existing assertions that conflict with the new hierarchy: the owner-backed `admin_client` list expects `['zoe']` rather than `['administrator', 'zoe']`; owner self-demotion/deactivation expects 403; and the concurrent two-admin mutation test configures `first-administrator` as owner and expects one owner mutation to return 200 while the reverse non-owner mutation returns 403, leaving one active administrator.

- [ ] **Step 2: Run the new admin tests and verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_admin.py -k "configured_owner or non_owner or owner_can_manage" -q
```

Expected: FAIL because the owner remains listed and current routes allow administrator creation or mutation.

- [ ] **Step 3: Add explicit server-side guards**

Add `store_ids` to `UserCreate` in `backend/app/schemas/admin.py`:

```python
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "user"] = "user"
    store_ids: list[int] = Field(default_factory=list)
```

Add imports and helpers near `UsersManager` in `backend/app/api/routes/admin.py`:

```python
from app.services.owner import is_owner, owner_username


def _require_can_assign_role(actor: User, role: str | None) -> None:
    if role == "admin" and not is_owner(actor):
        raise HTTPException(403, "只有最终管理员可以授予管理员角色")


def _require_can_manage_target(actor: User, target: User) -> None:
    if is_owner(target):
        raise HTTPException(403, "最终管理员账号受保护")
    if target.role == "admin" and not is_owner(actor):
        raise HTTPException(403, "只有最终管理员可以管理管理员账号")
```

Apply them at all mutation boundaries:

```python
# list_users
statement = select(User).order_by(User.username, User.id)
configured_owner = owner_username()
if configured_owner:
    statement = statement.where(User.username != configured_owner)
users = (await session.scalars(statement)).all()

# create_user, before constructing User
_require_can_assign_role(actor, body.role)
next_store_ids = [] if body.role == "admin" else sorted(set(body.store_ids))
await _require_stores(session, next_store_ids)

# after the new user has an id and before the audit/commit
session.add_all(
    StoreMember(store_id=store_id, user_id=user.id) for store_id in next_store_ids
)

# patch_user, immediately after the target 404 check and before snapshots/mutation
_require_can_manage_target(actor, user)
_require_can_assign_role(actor, body.role)

# delete_unused_user, immediately after the target 404 check
_require_can_manage_target(actor, user)
```

Return `_managed_user_payload(user, next_store_ids)` from creation and include `store_ids=next_store_ids` in the create audit snapshot so access assignment is truthful. Update the existing create-audit assertion to expect `"store_ids": []`. Do not change history-reference checks or the active-admin concurrency lock.

- [ ] **Step 4: Run admin API tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_admin.py -q
```

Expected: PASS. Forbidden requests return 403 without database changes; existing 409 business conflicts remain 409.

- [ ] **Step 5: Run backend regression and commit hierarchy enforcement**

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q
git add backend/app/schemas/admin.py backend/app/api/routes/admin.py backend/tests/api/test_admin.py
git commit -m "feat: enforce administrator hierarchy"
```

Expected: Ruff and pytest pass against `autolava_test`; commit includes only the admin route and its tests.

---

### Task 3: Build the User Master-Detail Workspace

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/auth/AuthProvider.tsx`
- Create: `frontend/src/admin/UserEditor.tsx`
- Rewrite: `frontend/src/admin/UsersPanel.tsx`
- Rewrite: `frontend/src/admin/UsersPanel.test.tsx`
- Modify: `frontend/src/auth/AuthProvider.test.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/pages/DatabasePage.test.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx`
- Modify: `frontend/src/pages/AdminPage.test.tsx`

**Interfaces:**
- Consumes: auth JSON `is_owner`, `useAuth()`, `useUnsavedChanges()`, `AdminUser.store_ids`, `AdminStore[]`.
- Produces: `AuthenticatedUser`, `UserDraft`, `draftForUser(user: AdminUser) -> UserDraft`, `UserEditor` props shown below, and `UsersPanel()` with no store-selection props.

- [ ] **Step 1: Write failing workspace tests for the approved UI**

Replace obsolete card/member/history assertions in `frontend/src/admin/UsersPanel.test.tsx` with tests using `UnsavedChangesProvider` and a hoisted auth state:

```tsx
const authState = vi.hoisted(() => ({
  user: { id: 1, username: "Nuru_Banmian", role: "admin" as const, is_owner: true },
}));

vi.mock("@/auth/AuthProvider", () => ({ useAuth: () => authState }));

function renderPanel() {
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false },
  } });
  return render(
    <QueryClientProvider client={client}>
      <UnsavedChangesProvider><UsersPanel /></UnsavedChangesProvider>
    </QueryClientProvider>,
  );
}

it("selects a user into one editor and removes duplicate management surfaces", async () => {
  mockUsers([
    { id: 2, username: "maria", role: "user", is_active: true, store_ids: [9] },
  ]);
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));

  expect(screen.getByRole("heading", { name: "编辑 maria" })).toBeInTheDocument();
  expect(screen.getAllByLabelText("重置密码（可选）")).toHaveLength(1);
  expect(screen.queryByText("门店成员")).not.toBeInTheDocument();
  expect(screen.queryByText("用户操作历史")).not.toBeInTheDocument();
  expect(screen.queryByText(/普通用户看不到管理中心/)).not.toBeInTheDocument();
  expect(screen.queryByText(/可访问 Roma/)).not.toBeInTheDocument();
});

it("renders administrators read-only for a non-owner", async () => {
  authState.user = { id: 3, username: "manager", role: "admin", is_owner: false };
  mockUsers([{ id: 4, username: "other-admin", role: "admin", is_active: true, store_ids: [] }]);
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /other-admin/ }));

  expect(screen.getByText("管理员账号只能由最终管理员编辑")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存用户" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "永久删除" })).not.toBeInTheDocument();
});

it("lets the owner edit another administrator", async () => {
  authState.user = { id: 1, username: "Nuru_Banmian", role: "admin", is_owner: true };
  mockUsers([{ id: 4, username: "other-admin", role: "admin", is_active: true, store_ids: [] }]);
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /other-admin/ }));

  expect(screen.getByRole("heading", { name: "编辑 other-admin" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存用户" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "永久删除" })).toBeInTheDocument();
  expect(screen.queryByLabelText("危险操作")).not.toBeInTheDocument();
  expect(screen.queryByText(/有历史记录.*只能停用/)).not.toBeInTheDocument();
  const footer = screen.getByTestId("user-editor-actions");
  expect(within(footer).getAllByRole("button").map((button) => button.textContent))
    .toEqual(["保存用户", "永久删除"]);
});

it("does not offer administrator creation to a non-owner", async () => {
  authState.user = { id: 3, username: "manager", role: "admin", is_owner: false };
  mockUsers([]);
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: "新建用户" }));

  expect(screen.getByRole("option", { name: "普通用户" })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "管理员" })).not.toBeInTheDocument();
});

it("guards user switches while the editor is dirty", async () => {
  authState.user = { id: 1, username: "Nuru_Banmian", role: "admin", is_owner: true };
  mockUsers([maria, operator]);
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "replacement123");
  await userEvent.click(screen.getByRole("button", { name: /operator/ }));

  expect(screen.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "继续编辑" }));
  expect(screen.getByRole("heading", { name: "编辑 maria" })).toBeInTheDocument();
});

it("creates a user with store access in the right-hand workspace", async () => {
  let posted: unknown;
  authState.user = { id: 1, username: "Nuru_Banmian", role: "admin", is_owner: true };
  mockUsers([], async (request) => { posted = await request.json(); });
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: "新建用户" }));
  await userEvent.type(screen.getByLabelText("用户名"), "operator");
  await userEvent.type(screen.getByLabelText("初始密码"), "operator123");
  await userEvent.click(screen.getByRole("checkbox", { name: "Roma" }));
  await userEvent.click(screen.getByRole("button", { name: "添加用户" }));

  await waitFor(() => expect(posted).toEqual({
    username: "operator",
    password: "operator123",
    role: "user",
    store_ids: [9],
  }));
});
```

Define the fixtures and helper in the test file:

```tsx
const roma = { id: 9, name: "Roma", address: "Via Roma", latitude: "41.9",
  longitude: "12.5", timezone: "Europe/Rome", is_active: true };
const maria = { id: 2, username: "maria", role: "user" as const,
  is_active: true, store_ids: [9] };
const operator = { id: 3, username: "operator", role: "user" as const,
  is_active: true, store_ids: [] };

function mockUsers(
  items: AdminUser[],
  captureCreate?: (request: Request) => Promise<void>,
) {
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json(items)),
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.post("/api/admin/users", async ({ request }) => {
      await captureCreate?.(request);
      return HttpResponse.json({ id: 10, username: "operator", role: "user",
        is_active: true, store_ids: [9] }, { status: 201 });
    }),
  );
}
```

Import `AdminUser` and let MSW's `onUnhandledRequest: "error"` prove that `/members` and `/operations` are never called.

Add regressions for inactive or unknown memberships: render every ID already present in `AdminUser.store_ids`, label unavailable entries, require explicit removal before save, and never silently filter them. Add deferred-request tests proving that controls are locked while their submitted draft is pending, user A state cannot initialize user B, stale errors cannot replace a newer result, and every successful backend mutation invalidates authoritative user data even when its request is superseded.

- [ ] **Step 2: Run user workspace tests and verify they fail**

```powershell
npm test -- --run src/admin/UsersPanel.test.tsx
```

Expected: FAIL because `UsersPanel` still renders cards, duplicate password/member/history UI, and accepts store-selection props.

- [ ] **Step 3: Add the authenticated owner type and keep auth fixtures explicit**

Keep the shared identity fields on `User` and add a session-only subtype in `frontend/src/api/types.ts`:

```ts
export interface User {
  id: number;
  username: string;
  role: UserRole;
}

export interface AuthenticatedUser extends User {
  is_owner: boolean;
}
```

In `frontend/src/auth/AuthProvider.tsx`, replace the imported `User` type with `AuthenticatedUser` and change `login(input): Promise<AuthenticatedUser>` plus both `api<AuthenticatedUser>` calls. Update the `admin` and `member` fixtures in `frontend/src/auth/AuthProvider.test.tsx`, and `/api/auth/me` fixtures in `frontend/src/App.test.tsx`, to include `is_owner: true` only for the configured-owner scenarios and `false` otherwise. Add one assertion that a login response with `is_owner: true` remains in `useAuth().user` without a refetch.

- [ ] **Step 4: Create the single user editor**

Create `frontend/src/admin/UserEditor.tsx` with these exported contracts:

```tsx
export interface UserDraft {
  username: string;
  role: UserRole;
  is_active: boolean;
  store_ids: number[];
  password: string;
}

export function draftForUser(user: AdminUser): UserDraft {
  return {
    username: user.username,
    role: user.role,
    is_active: user.is_active,
    store_ids: [...user.store_ids].sort((a, b) => a - b),
    password: "",
  };
}

export interface UserEditorProps {
  mode: "create" | "edit";
  user: AdminUser | null;
  stores: AdminStore[];
  isOwner: boolean;
  pending: boolean;
  error: Error | null;
  successVersion: number;
  onDirtyChange(dirty: boolean): void;
  onSubmit(draft: UserDraft): void;
  onDelete?(): void;
}
```

Implement one controlled form initialized from `draftForUser(user)` or this create value:

```ts
const createDraft: UserDraft = {
  username: "", role: "user", is_active: true, store_ids: [], password: "",
};
```

Render username as editable only in create mode; show the administrator role option only when `isOwner`; show active-store checkboxes only when `draft.role === "user"`; label the only password input `初始密码` in create mode and `重置密码（可选）` in edit mode. On submit, validate the required create-only fields and call `onSubmit(draft)`; API payload construction belongs to `UsersPanel`. Key each editor by selection and reset its clean baseline only when `successVersion` advances for that mounted editor. Disable every input and handler while `pending` so post-submit edits cannot be marked clean without being sent.

Render one footer row with `data-testid="user-editor-actions"`: `保存用户` on the left and `永久删除` on the right. Do not render a separate danger section or persistent deletion guidance. Use the existing Radix `AlertDialog` for confirmation; show the friendly deactivation guidance inside the editor only after a history-reference 409 response.

- [ ] **Step 5: Rewrite UsersPanel as selection and data coordinator**

`UsersPanel` must be exported with no props: `export function UsersPanel()`.

Use these selection and transition rules:

```tsx
type UserSelection = number | "new" | null;
const [selection, setSelection] = useState<UserSelection>(null);
const { user: actor } = useAuth();
const { markDirty, requestTransition } = useUnsavedChanges();

function select(next: UserSelection) {
  requestTransition(() => setSelection(next));
}
```

Construct the two mutation bodies in `UsersPanel` without sending an empty optional edit password:

```ts
function submitCreate(draft: UserDraft) {
  createUser.mutate({
    username: draft.username.trim(),
    password: draft.password,
    role: draft.role,
    store_ids: draft.role === "user" ? draft.store_ids : [],
  });
}

function submitEdit(draft: UserDraft) {
  if (typeof selection !== "number") return;
  patchUser.mutate({
    userId: selection,
    body: {
      role: draft.role,
      is_active: draft.is_active,
      store_ids: draft.role === "user" ? draft.store_ids : [],
      ...(draft.password ? { password: draft.password } : {}),
    },
  });
}
```

Define request and success bookkeeping in `UsersPanel` before creating the mutations:

```tsx
const requestIds = useRef(new Map<string, number>());
const [successVersions, setSuccessVersions] = useState<Record<string, number>>({});

function beginRequest(target: string) {
  const requestId = (requestIds.current.get(target) ?? 0) + 1;
  requestIds.current.set(target, requestId);
  return requestId;
}

function isLatest(target: string, requestId: number) {
  return requestIds.current.get(target) === requestId;
}

function recordSuccess(target: string) {
  setSuccessVersions((current) => ({
    ...current,
    [target]: (current[target] ?? 0) + 1,
  }));
}

const createSuccessVersion = successVersions.new ?? 0;
const editSuccessVersion = typeof selection === "number"
  ? successVersions[String(selection)] ?? 0
  : 0;
```

Scope mutation state by both selection and a monotonic request ID. Every successful create, patch, or delete must invalidate/refetch authoritative user and accessible-store data even if a newer request superseded it. After invalidation, only the latest request for that selection may clear dirty state, advance `successVersion`, display an error, or change selection. A refreshed list that no longer contains the selected numeric user must clear that selection and its dirty state.

The left rail is `hidden md:block`; the mobile `<select aria-label="用户">` is `md:hidden`. Each list item is a button with username, role badge, active state, and store count. The right side renders:

```tsx
if (selection === "new") return <UserEditor
  mode="create"
  user={null}
  stores={stores.data ?? []}
  isOwner={actor?.is_owner === true}
  pending={createUser.isPending}
  error={createUser.error}
  successVersion={createSuccessVersion}
  onDirtyChange={markDirty}
  onSubmit={submitCreate}
/>;
if (!selectedUser) return <p className="text-sm text-muted-foreground">请选择用户</p>;
if (selectedUser.role === "admin" && !actor?.is_owner) {
  return <section className="rounded-lg border bg-card p-4">
    <h2 className="font-medium">{selectedUser.username}</h2>
    <p className="text-sm text-muted-foreground">管理员账号只能由最终管理员编辑</p>
  </section>;
}
return <UserEditor
  mode="edit"
  user={selectedUser}
  stores={stores.data ?? []}
  isOwner={actor?.is_owner === true}
  pending={patchUser.isPending || deleteUser.isPending}
  error={patchUser.error ?? deleteError}
  successVersion={editSuccessVersion}
  onDirtyChange={markDirty}
  onSubmit={submitEdit}
  onDelete={() => deleteUser.mutate(selectedUser.id)}
/>;
```

Keep only `GET /admin/users`, `GET /admin/stores`, `POST /admin/users`, `PATCH /admin/users/{id}`, and `DELETE /admin/users/{id}`. On successful create/patch/delete, invalidate `usersKey`; invalidate `accessibleStoresKey` when `store_ids`, role, or active state may have changed. Preserve the friendly 409 deletion message. Call `markDirty` from `UserEditor.onDirtyChange`, clear it after successful submit/delete, and clear it on unmount.

Update `AdminPage.tsx` to call `<UsersPanel />` without the obsolete store-selection props so this task builds independently. Update only the user-related `AdminPage.test.tsx` harness/assertions to provide `AuthProvider` and `UnsavedChangesProvider`; keep the four-tab information architecture unchanged until Task 4. Set generic administrator fixtures in `App.test.tsx` and `DatabasePage.test.tsx` to `is_owner: false`; only explicit configured-owner scenarios use `true`.

- [ ] **Step 6: Run user and auth tests, then build**

```powershell
npm test -- --run src/admin/UsersPanel.test.tsx src/auth/AuthProvider.test.tsx src/App.test.tsx src/pages/DatabasePage.test.tsx src/pages/AdminPage.test.tsx
npm run build
```

Expected: selected-user editing, owner role options, non-owner read-only administrators, one password input, no member/history calls, dirty switching, auth typing, and TypeScript build all pass.

- [ ] **Step 7: Commit the user workspace**

```powershell
git add frontend/src/api/types.ts frontend/src/auth/AuthProvider.tsx frontend/src/admin/UserEditor.tsx frontend/src/admin/UsersPanel.tsx frontend/src/admin/UsersPanel.test.tsx frontend/src/auth/AuthProvider.test.tsx frontend/src/App.test.tsx frontend/src/pages/DatabasePage.test.tsx frontend/src/pages/AdminPage.tsx frontend/src/pages/AdminPage.test.tsx
git commit -m "feat: rebuild user administration workspace"
```

Expected: one commit containing the authenticated owner type and the complete user workspace.

---

### Task 4: Merge Store Details and Income Configuration into One Workspace

**Files:**
- Create: `frontend/src/admin/StoreDetailsCard.tsx`
- Create: `frontend/src/admin/StoreWorkspace.tsx`
- Create: `frontend/src/admin/StoreWorkspace.test.tsx`
- Modify: `frontend/src/admin/IncomeItemsPanel.tsx`
- Modify: `frontend/src/admin/IncomeItemsPanel.test.tsx`
- Modify: `frontend/src/admin/AdminLayout.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx`
- Modify: `frontend/src/pages/AdminPage.test.tsx`
- Delete: `frontend/src/admin/StoreSettingsPanel.tsx`
- Delete: `frontend/src/admin/StoreSettingsPanel.test.tsx`

**Interfaces:**
- Consumes: `AdminStore`, `useUnsavedChanges()`, existing store and income APIs.
- Produces: `StoreDetailsCard({ store, mode, onDirtyChange, onSaved, onDeleted })`; `IncomeItemsPanel({ storeId, onDirtyChange })`; `StoreWorkspace()`.

- [ ] **Step 1: Write failing controlled-income and merged-workspace tests**

Update the `IncomeItemsPanel` harness to the new controlled interface:

```tsx
const dirty = vi.fn();
render(<QueryClientProvider client={client}>
  <IncomeItemsPanel storeId={9} onDirtyChange={dirty} />
</QueryClientProvider>);
expect(screen.queryByLabelText("收入项目门店")).not.toBeInTheDocument();
await user.click(await screen.findByRole("checkbox", { name: "计入营业额 其他" }));
expect(dirty).toHaveBeenLastCalledWith(true);
await user.click(within(screen.getByRole("region", { name: "收入项目" }))
  .getByRole("button", { name: "保存" }));
await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
```

Create `frontend/src/admin/StoreWorkspace.test.tsx` with these core assertions:

```tsx
it("uses one store selection for independent details and income cards", async () => {
  mockStoreWorkspace();
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));

  expect(screen.getByRole("heading", { name: "门店资料" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "收入项目" })).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "门店资料" }))
    .getByRole("button", { name: "保存" })).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "收入项目" }))
    .getByRole("button", { name: "保存" })).toBeInTheDocument();
  expect(screen.getAllByLabelText("门店")).toHaveLength(1);
});

it("guards store switches when either card is dirty", async () => {
  mockTwoStores();
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.clear(screen.getByLabelText("门店名称 Roma"));
  await userEvent.type(screen.getByLabelText("门店名称 Roma"), "Roma Centro");
  await userEvent.click(screen.getByRole("button", { name: /Milano/ }));

  expect(screen.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
  expect(await screen.findByLabelText("门店名称 Milano")).toBeInTheDocument();
});

const publishedIncomeConfig = {
  store_id: 9,
  version_id: 4,
  version: 4,
  enabled: true,
  formula: "营业额 = 现金",
  created_at: "2026-07-17T08:00:00Z",
  items: [
    { id: 41, category_id: 1, name: "现金", include_in_total: true,
      is_active: true, sort_order: 0 },
  ],
};

it("keeps store and income saves independent when one request fails", async () => {
  let incomePublished = false;
  mockStoreWorkspace({
    patchStore: () => HttpResponse.json({ detail: "门店保存失败" }, { status: 500 }),
    publishIncome: () => {
      incomePublished = true;
      return HttpResponse.json(publishedIncomeConfig);
    },
  });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.click(within(screen.getByRole("region", { name: "门店资料" }))
    .getByRole("button", { name: "保存" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("门店保存失败");

  await userEvent.click(within(screen.getByRole("region", { name: "收入项目" }))
    .getByRole("button", { name: "保存" }));
  await waitFor(() => expect(incomePublished).toBe(true));
  expect(screen.getByRole("alert")).toHaveTextContent("门店保存失败");
});
```

Add a deferred-response regression: start a Roma details save, explicitly discard the dirty draft and switch to Milano, then resolve the Roma save. Assert the Roma store query is refreshed, but Milano remains selected and its details/income drafts are unchanged. Add the inverse failure case and assert a stale Roma error is not rendered in the Milano cards.

Implement `mockStoreWorkspace` with optional handler callbacks matching the two functions shown in the test. Wrap `renderWorkspace()` with `UnsavedChangesProvider`. Mock exact responses for `/admin/stores`, `/income-config/{id}/current`, and `/admin/income-categories?store_id={id}`.

- [ ] **Step 2: Run the store tests and verify the new contracts are absent**

```powershell
npm test -- --run src/admin/IncomeItemsPanel.test.tsx src/admin/StoreWorkspace.test.tsx
```

Expected: FAIL because `StoreWorkspace` does not exist and `IncomeItemsPanel` still owns a duplicate store selector.

- [ ] **Step 3: Convert IncomeItemsPanel to a controlled card**

Change its public contract:

```tsx
export interface IncomeItemsPanelProps {
  storeId: number;
  onDirtyChange(dirty: boolean): void;
}

export function IncomeItemsPanel({ storeId, onDirtyChange }: IncomeItemsPanelProps) {
```

Replace every `selectedStoreId` reference with `storeId`, remove `storesKey`, the `/admin/stores` query, the `<select>`, and `onSelectedStoreChange`. Preserve the existing stale-response checks by keeping `draftStoreId`. Report state upward:

```tsx
useEffect(() => {
  onDirtyChange(isDirty);
}, [isDirty, onDirtyChange]);

useEffect(() => () => onDirtyChange(false), [onDirtyChange]);
```

Replace the current root `<div className="space-y-4">` with `<section className="space-y-4 rounded-lg border bg-card p-4" aria-labelledby="income-items-title">`, insert `<h2 id="income-items-title" className="font-medium">收入项目</h2>` before the error/content nodes, and close with `</section>`. Keep the enabled toggle, preview, editable list, archive area, and publish button inside that section.

Change the publish button's visible text from `保存并发布` to exactly `保存`; do not change version publication, archive/restore/delete, or per-store query invalidation. Every successful lifecycle or publish request still invalidates its captured store ID even after selection changes. Only a still-mounted request whose captured `storeId` matches the mounted prop may replace draft items, clear dirty state, or display an error.

- [ ] **Step 4: Extract the controlled store details card**

Create `frontend/src/admin/StoreDetailsCard.tsx` with this public interface:

```tsx
export interface StoreDetailsCardProps {
  mode: "create" | "edit";
  store: AdminStore | null;
  onDirtyChange(dirty: boolean): void;
  onSaved(store: AdminStore): void;
  onDeleted(storeId: number): void;
}
```

Move create, patch, delete, `StoreLocationPicker`, accessible-store invalidation, and friendly 409 deletion handling from `StoreSettingsPanel`. Use controlled `name` and `location` state so dirty state is deterministic:

```tsx
const initial = store ? {
  name: store.name,
  location: { label: store.address, latitude: Number(store.latitude),
    longitude: Number(store.longitude), timezone: store.timezone },
} : { name: "", location: null };
const dirty = name !== initial.name || JSON.stringify(location) !== JSON.stringify(initial.location);
```

The card heading is `新建门店` or `门店资料`. Give the card `role="region"` through `aria-labelledby`. In edit mode, render one compact desktop row in this exact order: name input, location summary, `修改位置`, `保存`; allow the row to wrap naturally on narrow screens. The edit button text is exactly `保存`; create mode keeps `添加门店`. Keep deactivate and permanent delete in the store lifecycle area.

Track a monotonic request ID and mounted flag inside the card. Every successful create/patch/delete invalidates `['admin','stores']` and accessible stores even if the component unmounted or the request was superseded. Only a still-mounted latest request may call `onDirtyChange(false)`, `onSaved(response)`, `onDeleted(id)`, or display an error. Disable all card controls while its request is pending.

- [ ] **Step 5: Create StoreWorkspace and aggregate dirty sources**

Create `frontend/src/admin/StoreWorkspace.tsx`:

```tsx
type StoreSelection = number | "new" | null;

export function StoreWorkspace() {
  const [selection, setSelection] = useState<StoreSelection>(null);
  const [detailsDirty, setDetailsDirty] = useState(false);
  const [incomeDirty, setIncomeDirty] = useState(false);
  const { markDirty, requestTransition } = useUnsavedChanges();
  const stores = useQuery({ queryKey: ["admin", "stores"],
    queryFn: () => api<AdminStore[]>("/admin/stores") });

  useEffect(() => markDirty(detailsDirty || incomeDirty),
    [detailsDirty, incomeDirty, markDirty]);
  useEffect(() => () => markDirty(false), [markDirty]);

  function select(next: StoreSelection) {
    requestTransition(() => {
      setDetailsDirty(false);
      setIncomeDirty(false);
      setSelection(next);
    });
  }
}
```

After the state/transition block, return the responsive selector and right-hand cards described below; do not add another store query inside either child.

Desktop uses `md:grid md:grid-cols-[14rem_minmax(0,1fr)]`; its store rail is `hidden md:block`. Mobile uses one `<select aria-label="门店" className="md:hidden">` and an adjacent `新建门店` button. For an existing selection render both cards; for `"new"`, render only `StoreDetailsCard mode="create"`.

On store create, invalidate `['admin','stores']` and accessible stores, then select the returned ID. On deletion, select the first remaining store after refetch. Do not let a details save clear `incomeDirty`, or an income publish clear `detailsDirty`.

Render both child cards with `key={selection}`. A child success callback must verify that the captured store ID still equals the current numeric selection before changing selection or card state; authoritative invalidation is never skipped. Scope visible errors to the store ID and operation that produced them so switching stores cannot carry an error into the new workspace.

- [ ] **Step 6: Integrate the three-tab shell in the same buildable task**

Update `AdminPage.test.tsx` before implementation:

```tsx
expect((await screen.findAllByRole("tab")).map((tab) => tab.textContent)).toEqual([
  "门店与收入", "用户与权限", "系统状态",
]);
expect(screen.getByRole("tab", { name: "门店与收入" }))
  .toHaveAttribute("aria-selected", "true");
```

Add a dirty-tab test that edits the selected store name, clicks `系统状态`, cancels the `放弃未保存的修改？` dialog, and verifies `门店与收入` remains selected. Run `npm test -- --run src/pages/AdminPage.test.tsx` and expect the old four-tab shell to fail.

Replace the tab contract in `AdminLayout.tsx`:

```tsx
export type AdminTab = "stores" | "users" | "status";

export const orderedAdminTabs: { value: AdminTab; label: string }[] = [
  { value: "stores", label: "门店与收入" },
  { value: "users", label: "用户与权限" },
  { value: "status", label: "系统状态" },
];
```

In `AdminPage.tsx`, default invalid or missing query state to `stores`, call `requestTransition()` before changing the query string, and render exactly:

```tsx
<AdminLayout tab={tab} onTabChange={selectTab} panels={{
  stores: <StoreWorkspace />,
  users: <UsersPanel />,
  status: <SystemStatusPanel />,
}} />
```

Delete `StoreSettingsPanel.tsx` and its obsolete test only after their lifecycle assertions exist in `StoreWorkspace.test.tsx`. This task owns the shell integration because deleting the old panel and changing the controlled income interface would otherwise leave `AdminPage` uncompilable between tasks.

- [ ] **Step 7: Run store, shell, and build verification**

```powershell
npm test -- --run src/admin/IncomeItemsPanel.test.tsx src/admin/StoreWorkspace.test.tsx src/pages/AdminPage.test.tsx
npm run build
```

Expected: controlled income tests, compact store details, both `保存` buttons, merged layout, independent saving, dirty aggregation, responsive selectors, store lifecycle, three-tab shell, guarded tab transitions, and TypeScript build pass.

- [ ] **Step 8: Commit the merged store workspace and shell**

```powershell
git add frontend/src/admin/IncomeItemsPanel.tsx frontend/src/admin/IncomeItemsPanel.test.tsx frontend/src/admin/StoreDetailsCard.tsx frontend/src/admin/StoreWorkspace.tsx frontend/src/admin/StoreWorkspace.test.tsx frontend/src/admin/StoreSettingsPanel.tsx frontend/src/admin/StoreSettingsPanel.test.tsx frontend/src/admin/AdminLayout.tsx frontend/src/pages/AdminPage.tsx frontend/src/pages/AdminPage.test.tsx
git commit -m "feat: merge store and income administration"
```

Expected: the deleted paths, new workspace files, and final three-tab shell are recorded in one independently buildable commit.

---

### Task 5: Polish System Status and Complete Acceptance Coverage

**Files:**
- Modify: `frontend/src/admin/SystemStatusPanel.tsx`
- Modify: `frontend/src/admin/SystemStatusPanel.test.tsx`
- Modify: `frontend/tests/admin-flow.spec.ts`

**Interfaces:**
- Consumes: the final `StoreWorkspace`, `UsersPanel`, three-tab `AdminPage`, and existing `SystemStatusPanel` semantics.
- Produces: visual-only status hierarchy, final browser acceptance flow, and full release evidence.

- [ ] **Step 1: Apply visual-only status-card polish**

Do not alter any query, timestamp, completeness, or alert logic in `SystemStatusPanel.tsx`. Only make the regions match the approved visual hierarchy:

Use `grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.7fr)]` on the existing outer container and `space-y-3 rounded-xl border bg-card p-5 shadow-sm` on each of the two existing named sections. Preserve their current `aria-labelledby` attributes and children.

Add assertions in `SystemStatusPanel.test.tsx` that `运行状态` and `未解决告警` remain named regions; retain every existing truthfulness, UTC, partial, error, and multi-store assertion unchanged.

- [ ] **Step 2: Update the browser acceptance flow**

In `frontend/tests/admin-flow.spec.ts`:

- Return `is_owner: true` from both auth mocks.
- Expect tabs `门店与收入`, `用户与权限`, `系统状态`.
- Select `Roma` once through the shared store selector, then publish income without visiting another tab.
- Open `用户与权限`, click `新建用户`, select the Roma membership, and submit the right-side form; expect `{ username: "operator", password: "operator-123", role: "user", store_ids: [1] }`.
- Return to `门店与收入`, click `新建门店`, and complete the existing map flow.
- Assert there are zero visible texts matching `门店成员`, `用户操作历史`, or `普通用户看不到管理中心`.
- Within the `门店资料` and `收入项目` regions, expect the primary button text `保存`; assert `保存门店资料` and `保存并发布` are absent.
- In the selected user editor, assert `保存用户` precedes `永久删除` in the same footer, `永久删除` is the rightmost action, and no separate `危险操作` region or persistent history-deletion guidance exists.

Use these key assertions:

```ts
await expect(page.getByRole("tab")).toHaveText([
  "门店与收入", "用户与权限", "系统状态",
]);
await expect(page.getByRole("tab", { name: "门店与收入" }))
  .toHaveAttribute("aria-selected", "true");
await expect(page.getByText("门店成员")).toHaveCount(0);
await expect(page.getByText("用户操作历史")).toHaveCount(0);
```

- [ ] **Step 3: Run frontend unit, build, and browser acceptance**

```powershell
npm test -- --run
npm run build
npx playwright test tests/admin-flow.spec.ts
```

Expected: 22 or more Vitest files pass, production TypeScript/Vite build succeeds, and the admin browser flow passes at desktop viewport.

- [ ] **Step 4: Run full release verification**

From `backend` with `AUTOLAVA_DATABASE_URL` targeting `autolava_test`:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
```

From `frontend`:

```powershell
npm test -- --run
npm run build
npx playwright test
```

Expected: backend lint/tests/coverage, all frontend unit tests, production build, and the complete Playwright suite pass. Confirm `git status --short` shows only intended implementation changes before the final commit.

- [ ] **Step 5: Commit status polish and acceptance coverage**

```powershell
git add frontend/src/admin/SystemStatusPanel.tsx frontend/src/admin/SystemStatusPanel.test.tsx frontend/tests/admin-flow.spec.ts
git commit -m "test: complete management center acceptance"
```

Expected: final task commit contains only status styling/tests and the acceptance flow; the three-tab shell was already integrated in Task 4.

## Final Acceptance Checklist

- [ ] `Nuru_Banmian` appears nowhere in production application modules; it exists only as deployment configuration, documentation, and test fixture data.
- [ ] Owner APIs and non-owner administrator restrictions are enforced server-side with 403 responses and no audit mutation.
- [ ] User management has one password field, one membership editor, no member panel, no history panel, no summary card, and no admin-visibility reminder.
- [ ] User deletion is the rightmost editor-footer action; there is no separate danger card or persistent deletion guidance, while confirmation and history-conflict guidance still work.
- [ ] Store details and income items share one selection but retain separate save buttons and separate error states.
- [ ] Store details are one compact desktop row, and both store and income primary buttons read `保存`; income still publishes a version.
- [ ] User, store, income, and tab switches cannot silently discard dirty state.
- [ ] Mobile uses top selectors; desktop uses left rails.
- [ ] System status and database history behavior remain semantically unchanged.
- [ ] Backend Ruff/pytest, frontend Vitest/build, and Playwright all pass.
