# Phase 1 Usability 01: Shell and Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved blue design system, persistent store context, role-aware desktop/mobile navigation, mobile More page, and Chinese login experience.

**Architecture:** Keep routing and authentication in the existing React providers. Add small presentation-focused modules for navigation metadata, friendly errors, and the More page; persist only the selected store ID and always revalidate it against the accessible-store response.

**Tech Stack:** React, TypeScript, React Router, TanStack Query, Tailwind CSS 4, Vitest, Testing Library, Playwright.

## Global Constraints

- Use the approved blue primary theme; do not retain the old green theme.
- Mobile navigation is exactly 首页、记账、记录、更多.
- 普通用户 never sees 管理中心; backend authorization remains authoritative.
- Support widths from 320px without page-level horizontal scrolling or bottom-navigation overlap.
- All user-facing authentication and network errors are Chinese.

---

### Task 1: Friendly API Errors

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `friendlyApiError(error: unknown, fallback: string): string`
- Consumes: existing `ApiError`

- [ ] **Step 1: Write failing localization tests**

```ts
import { ApiError, friendlyApiError } from "@/api/client";

it("localizes known technical messages", () => {
  expect(friendlyApiError(new ApiError(401, "Invalid credentials"), "登录失败"))
    .toBe("用户名或密码错误，请重新输入");
  expect(friendlyApiError(new ApiError(403, "Inactive user"), "登录失败"))
    .toBe("这个账号已停用，请联系管理员");
});
```

- [ ] **Step 2: Run the test and verify failure**

Run: `npm test -- src/api/client.test.ts`
Expected: FAIL because `friendlyApiError` is not exported.

- [ ] **Step 3: Implement exact error mapping**

```ts
const friendlyMessages: Record<string, string> = {
  "Invalid credentials": "用户名或密码错误，请重新输入",
  "Inactive user": "这个账号已停用，请联系管理员",
  "Income configuration version does not match": "收入项目刚刚发生变化，页面已为你重新加载，请确认金额后再次保存",
};

export function friendlyApiError(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  const mapped = friendlyMessages[error.detail];
  if (mapped) return mapped;
  if (/^[\x00-\x7f\s]+$/.test(error.detail)) {
    if (error.status === 403) return "你没有权限执行这个操作";
    if (error.status === 409) return "数据已经发生变化，请刷新后重试";
    if (error.status >= 500) return "服务器暂时不可用，请稍后重试";
  }
  return error.detail || fallback;
}
```

- [ ] **Step 4: Run focused tests**

Run: `npm test -- src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat: localize frontend api errors"
```

### Task 2: Blue Design Tokens

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: global Tailwind theme tokens consumed by every later UI task.

- [ ] **Step 1: Add a theme-token assertion**

```ts
it("loads the shared application shell", async () => {
  renderApplication("/");
  expect(await screen.findByText("AutoLava AI")).toBeInTheDocument();
  expect(document.documentElement).toBeTruthy();
});
```

- [ ] **Step 2: Run the application test**

Run: `npm test -- src/App.test.tsx`
Expected: existing test baseline is recorded before visual-token changes.

- [ ] **Step 3: Replace root tokens with the approved palette**

```css
:root {
  --radius: 0.875rem;
  --background: oklch(0.985 0.006 250);
  --foreground: oklch(0.24 0.03 255);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.24 0.03 255);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.24 0.03 255);
  --primary: oklch(0.55 0.19 255);
  --primary-foreground: oklch(0.99 0 0);
  --secondary: oklch(0.95 0.018 250);
  --secondary-foreground: oklch(0.28 0.04 255);
  --muted: oklch(0.96 0.012 250);
  --muted-foreground: oklch(0.5 0.035 255);
  --accent: oklch(0.93 0.035 250);
  --accent-foreground: oklch(0.3 0.08 255);
  --destructive: oklch(0.58 0.22 27);
  --border: oklch(0.9 0.018 250);
  --input: oklch(0.9 0.018 250);
  --ring: oklch(0.62 0.16 255);
}
```

- [ ] **Step 4: Run unit and build checks**

Run: `npm test -- src/App.test.tsx && npm run build`
Expected: PASS and Vite build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/index.css frontend/src/App.test.tsx
git commit -m "style: apply approved blue design tokens"
```

### Task 3: Persistent Store Context

**Files:**
- Modify: `frontend/src/stores/StoreProvider.tsx`
- Create: `frontend/src/stores/StoreProvider.test.tsx`

**Interfaces:**
- Produces: `STORE_SELECTION_KEY = "autolava:selected-store"`
- Preserves: `useStore().selected` and `useStore().select(id)`

- [ ] **Step 1: Test restore and invalid-selection fallback**

```tsx
it("restores a permitted store and clears a revoked store", async () => {
  localStorage.setItem("autolava:selected-store", "2");
  server.use(http.get("/api/stores/accessible", () => HttpResponse.json([
    { id: 2, name: "Roma", timezone: "Europe/Rome" },
  ])));
  render(<StoreProvider><Probe /></StoreProvider>);
  expect(await screen.findByText("Roma")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test and verify failure**

Run: `npm test -- src/stores/StoreProvider.test.tsx`
Expected: FAIL because selection is not restored.

- [ ] **Step 3: Persist only validated IDs**

```tsx
export const STORE_SELECTION_KEY = "autolava:selected-store";
const initialId = Number(localStorage.getItem(STORE_SELECTION_KEY)) || null;
const [selectedId, setSelectedId] = useState<number | null>(initialId);

useEffect(() => {
  if (!stores.length) return;
  if (selectedId !== null && stores.some((store) => store.id === selectedId)) {
    localStorage.setItem(STORE_SELECTION_KEY, String(selectedId));
    return;
  }
  const fallback = stores[0]?.id ?? null;
  setSelectedId(fallback);
  if (fallback === null) localStorage.removeItem(STORE_SELECTION_KEY);
  else localStorage.setItem(STORE_SELECTION_KEY, String(fallback));
}, [selectedId, stores]);
```

- [ ] **Step 4: Run store tests**

Run: `npm test -- src/stores/StoreProvider.test.tsx`
Expected: PASS for restore, revoked selection, and empty store list.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/StoreProvider.tsx frontend/src/stores/StoreProvider.test.tsx
git commit -m "feat: persist validated store selection"
```

### Task 4: Role-Aware Shell and Mobile More Page

**Files:**
- Create: `frontend/src/navigation/modules.ts`
- Modify: `frontend/src/layouts/AppShell.tsx`
- Create: `frontend/src/pages/MorePage.tsx`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: `navigationFor(role: UserRole, surface: "desktop" | "mobile")`
- Routes: `/more`; existing `/charts` and `/admin`

- [ ] **Step 1: Test exact mobile navigation and role visibility**

```tsx
it("shows four mobile entries and hides management from regular users", async () => {
  renderApplication("/more", { role: "user" });
  const nav = await screen.findByRole("navigation", { name: "移动导航" });
  expect(within(nav).getAllByRole("link")).toHaveLength(4);
  expect(within(nav).getByText("更多")).toBeInTheDocument();
  expect(screen.queryByText("管理中心")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/App.test.tsx`
Expected: FAIL because the existing mobile navigation has more than four items.

- [ ] **Step 3: Define navigation metadata**

```ts
export const mobileModules = [
  { to: "/", label: "首页", end: true },
  { to: "/ledger", label: "记账" },
  { to: "/database", label: "记录" },
  { to: "/more", label: "更多" },
] as const;
```

- [ ] **Step 4: Implement the More page role branches**

```tsx
export function MorePage() {
  const { user, logout, isLoggingOut } = useAuth();
  return <section className="grid gap-4">
    <h1 className="text-2xl font-semibold">更多</h1>
    <nav aria-label="更多功能" className="grid gap-2">
      <Link to="/charts">经营分析</Link>
      <StorePicker />
      <Link to="/account/password">修改密码</Link>
      {user?.role === "admin" && <Link to="/admin">管理中心</Link>}
      {user?.role === "admin" && <Link to="/admin?tab=status">系统状态</Link>}
    </nav>
    <Button disabled={isLoggingOut} onClick={() => void logout()}>退出登录</Button>
  </section>;
}
```

- [ ] **Step 5: Register `/more` and rebuild AppShell**

Use a desktop blue sidebar at `md` widths and the four-entry bottom navigation below `md`. Keep the main content `pb-24 md:pb-6` so the bottom bar never covers content.

```tsx
{ path: "more", element: <MorePage /> }
{ path: "account/password", element: <AccountPasswordPage /> }
```

- [ ] **Step 6: Run tests and build**

Run: `npm test -- src/App.test.tsx && npm run build`
Expected: PASS; user has no management entry, admin does.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/navigation/modules.ts frontend/src/layouts/AppShell.tsx frontend/src/pages/MorePage.tsx frontend/src/router.tsx frontend/src/App.test.tsx
git commit -m "feat: add responsive role-aware application shell"
```

### Task 5: Approved Login Page

**Files:**
- Modify: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/pages/LoginPage.test.tsx`

**Interfaces:**
- Consumes: `friendlyApiError`
- Preserves: `useAuth().login({ username, password, remember })`

- [ ] **Step 1: Test Chinese states and password visibility**

```tsx
it("shows a Chinese disabled-account message", async () => {
  mockLoginError(new ApiError(403, "Inactive user"));
  renderLogin();
  await userEvent.type(screen.getByLabelText("用户名"), "disabled");
  await userEvent.type(screen.getByLabelText("密码"), "Password123");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("这个账号已停用，请联系管理员");
});
```

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/pages/LoginPage.test.tsx`
Expected: FAIL because the raw backend detail is shown.

- [ ] **Step 3: Implement the split blue login layout**

Add a brand panel, username/password fields, password visibility button, full-width loading button, and `friendlyApiError(caught, "登录失败，请稍后重试")`. Keep native labels and password autocomplete.

```tsx
const [showPassword, setShowPassword] = useState(false);
<Input autoComplete="current-password" id="password" name="password" type={showPassword ? "text" : "password"} required />
<Button aria-label={showPassword ? "隐藏密码" : "显示密码"} onClick={() => setShowPassword((value) => !value)} type="button" variant="ghost" />
```

- [ ] **Step 4: Run tests and build**

Run: `npm test -- src/pages/LoginPage.test.tsx src/auth/AuthProvider.test.tsx && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LoginPage.tsx frontend/src/pages/LoginPage.test.tsx
git commit -m "feat: redesign login with Chinese feedback"
```

### Task 6: Self-Service Password Change

**Files:**
- Modify: `backend/app/schemas/auth.py`
- Modify: `backend/app/api/routes/auth.py`
- Modify: `backend/tests/api/test_auth.py`
- Create: `frontend/src/pages/AccountPasswordPage.tsx`
- Create: `frontend/src/pages/AccountPasswordPage.test.tsx`
- Modify: `frontend/src/router.tsx`

**Interfaces:**
- Produces: `POST /auth/password` with current and new password.

- [ ] **Step 1: Add the failing API test**

```py
async def test_user_changes_own_password(client, user_headers):
    response = await client.post("/auth/password", json={"current_password": "OldPassword1", "new_password": "NewPassword2"}, headers=user_headers)
    assert response.status_code == 204
```

- [ ] **Step 2: Run and verify failure**

Run: `pytest backend/tests/api/test_auth.py -q`
Expected: FAIL with 404 because the route does not exist.

- [ ] **Step 3: Implement the authenticated endpoint**

```py
class PasswordChange(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

@router.post("/password", status_code=204)
async def change_password(body: PasswordChange, session: Session, user: CurrentUser) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(422, "当前密码不正确")
    user.password_hash = hash_password(body.new_password)
    await session.commit()
```

- [ ] **Step 4: Build and test the account form**

The page contains current password, new password, confirmation, and Chinese mismatch feedback. On success navigate back to `/more` with status `密码已更新`.

Run: `npm test -- src/pages/AccountPasswordPage.test.tsx`
Expected: PASS after implementation.

- [ ] **Step 5: Run auth gates and commit**

Run: `pytest backend/tests/api/test_auth.py -q && npm test -- src/pages/AccountPasswordPage.test.tsx && npm run build`
Expected: PASS.

```bash
git add backend/app/schemas/auth.py backend/app/api/routes/auth.py backend/tests/api/test_auth.py frontend/src/pages/AccountPasswordPage.tsx frontend/src/pages/AccountPasswordPage.test.tsx frontend/src/router.tsx
git commit -m "feat: let users change their own password"
```

### Task 7: Responsive Shell Acceptance

**Files:**
- Modify: `frontend/tests/responsive.spec.ts`

**Interfaces:**
- Consumes: final shell, login, and More page.

- [ ] **Step 1: Add 320px assertions**

```ts
test("mobile shell has four reachable entries without overlap", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await loginAs(page, "user");
  await expect(page.getByRole("navigation", { name: "移动导航" }).getByRole("link")).toHaveCount(4);
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 320);
});
```

- [ ] **Step 2: Run the focused browser test**

Run: `npm run test:e2e -- responsive.spec.ts`
Expected: PASS at 320px and desktop viewport.

- [ ] **Step 3: Run the full frontend gate**

Run: `npm test && npm run build && npm run test:e2e`
Expected: all frontend checks PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/responsive.spec.ts
git commit -m "test: cover responsive shell and role navigation"
```
