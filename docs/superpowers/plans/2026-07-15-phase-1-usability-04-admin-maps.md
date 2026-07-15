# Phase 1 Usability 04: Admin and Maps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the ordered admin center, safe user/store lifecycle, map-based store selection with switchable providers, and truthful system status.

**Architecture:** Split the monolithic AdminPage into four route-local panels while retaining existing APIs and query keys. Add a small map adapter boundary on the frontend; Leaflet/OSM is the default renderer and the existing Open-Meteo geocode endpoint supplies place results. Coordinates remain in API payloads but never appear as user-editable fields.

**Tech Stack:** React, TypeScript, TanStack Query, Leaflet, FastAPI, SQLAlchemy async, Pytest, Vitest, Playwright.

## Global Constraints

- Admin tab order is 收入项目、用户与权限、门店设置、系统状态.
- Ordinary users cannot see or call admin functions.
- Referenced users/stores are disabled or archived, not physically deleted.
- Latitude and longitude never appear in user forms.
- Map provider selection is replaceable without changing saved store data or business components.
- System status shows only real data; never fabricate healthy state.

---

### Task 1: Split the Admin Center

**Files:**
- Create: `frontend/src/admin/AdminLayout.tsx`
- Create: `frontend/src/admin/IncomeItemsPanel.tsx`
- Create: `frontend/src/admin/UsersPanel.tsx`
- Create: `frontend/src/admin/StoreSettingsPanel.tsx`
- Create: `frontend/src/admin/SystemStatusPanel.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx`
- Modify: `frontend/src/pages/AdminPage.test.tsx`

**Interfaces:**
- Produces: `AdminTab = "income" | "users" | "stores" | "status"`
- Preserves: existing `/admin` route; query parameter `tab` selects a panel.

- [ ] **Step 1: Test exact order and default tab**

```tsx
const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
expect(tabs).toEqual(["收入项目", "用户与权限", "门店设置", "系统状态"]);
expect(screen.getByRole("tab", { name: "收入项目" })).toHaveAttribute("aria-selected", "true");
```

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/pages/AdminPage.test.tsx`
Expected: FAIL because current tabs are users/stores/members/categories/alerts/tasks.

- [ ] **Step 3: Add typed tab routing**

```tsx
export type AdminTab = "income" | "users" | "stores" | "status";
const orderedTabs: { value: AdminTab; label: string }[] = [
  { value: "income", label: "收入项目" },
  { value: "users", label: "用户与权限" },
  { value: "stores", label: "门店设置" },
  { value: "status", label: "系统状态" },
];
```

- [ ] **Step 4: Move existing queries without changing endpoint behavior**

Each panel owns only its needed query/mutations. `AdminPage` owns the tab shell and selected current store. Do not keep duplicate requests in the parent.

- [ ] **Step 5: Run tests and build**

Run: `npm test -- src/pages/AdminPage.test.tsx && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/admin frontend/src/pages/AdminPage.tsx frontend/src/pages/AdminPage.test.tsx
git commit -m "refactor: split ordered admin center panels"
```

### Task 2: Income Items Panel

**Files:**
- Modify: `frontend/src/admin/IncomeItemsPanel.tsx`
- Create: `frontend/src/admin/IncomeItemsPanel.test.tsx`
- Modify: `backend/tests/api/test_income_config.py`

**Interfaces:**
- Consumes: `/income-config/{store_id}/current`, publish, archive, restore, delete-unused endpoints.
- Produces: ordered `IncomeConfigPublishBody`.

- [ ] **Step 1: Test formula preview and referenced deletion rule**

```tsx
expect(screen.getByText("营业额 = 现金 + 刷卡；“其他”只记录，不计入营业额")).toBeInTheDocument();
await userEvent.click(screen.getByRole("checkbox", { name: "计入营业额 其他" }));
expect(screen.getByText("营业额 = 现金 + 刷卡 + 其他")).toBeInTheDocument();
```

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/admin/IncomeItemsPanel.test.tsx`
Expected: FAIL because the panel does not exist.

- [ ] **Step 3: Implement list operations**

Keep one local draft array, reindex `sort_order` after up/down moves, and publish once on save.

```ts
const move = (index: number, offset: -1 | 1) => setItems((current) => {
  const next = [...current];
  [next[index], next[index + offset]] = [next[index + offset], next[index]];
  return next.map((item, sort_order) => ({ ...item, sort_order }));
});
```

- [ ] **Step 4: Verify backend archive/delete rules**

Add tests that unused categories delete with 204 and referenced categories return 409 with a Chinese-friendly code/detail. Keep history snapshots untouched.

- [ ] **Step 5: Run focused tests**

Run: `pytest backend/tests/api/test_income_config.py -q && npm test -- src/admin/IncomeItemsPanel.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/admin/IncomeItemsPanel.tsx frontend/src/admin/IncomeItemsPanel.test.tsx backend/tests/api/test_income_config.py
git commit -m "feat: add versioned income items admin panel"
```

### Task 3: User Lifecycle and Store Assignment

**Files:**
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/app/api/routes/admin.py`
- Modify: `backend/tests/api/test_admin.py`
- Modify: `frontend/src/admin/UsersPanel.tsx`
- Create: `frontend/src/admin/UsersPanel.test.tsx`

**Interfaces:**
- Produces: user patch supports `role`, `password`, and `is_active`.
- Preserves: last-admin and current-admin protection.

- [ ] **Step 1: Add role and lifecycle API tests**

```py
async def test_admin_can_assign_user_role_and_stores(client, admin_headers, user, store):
    response = await client.patch(f"/admin/users/{user.id}", json={"role": "user", "store_ids": [store.id]}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["store_ids"] == [store.id]
```

Also lock the deletion rule:

```py
async def test_user_with_audit_history_cannot_be_deleted(client, admin_headers, audited_user):
    response = await client.delete(f"/admin/users/{audited_user.id}", headers=admin_headers)
    assert response.status_code == 409
```

- [ ] **Step 2: Run and verify contract gap**

Run: `pytest backend/tests/api/test_admin.py -q`
Expected: FAIL if the existing patch schema lacks role/store assignment.

- [ ] **Step 3: Extend the explicit schema**

```py
class UserPatch(BaseModel):
    password: Password | None = None
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    store_ids: list[int] | None = None
```

Patch role and members in one transaction, audit before/after, reject self-disable and last-admin demotion. Add `DELETE /admin/users/{user_id}`: return 409 when ledger creator/updater or audit references exist; for a never-used mistaken account, remove current store memberships and then delete the user.

- [ ] **Step 4: Build the approved user list/editor**

Show username, role, accessible stores, active state, reset password, and an inline editor. Hide store checkboxes for admins because they receive all-store access.

- [ ] **Step 5: Test ordinary-user menu isolation**

```tsx
expect(screen.getByText("普通用户看不到管理中心，只能使用已分配门店的日常经营页面。")).toBeInTheDocument();
```

- [ ] **Step 6: Run tests**

Run: `pytest backend/tests/api/test_admin.py backend/tests/services/test_access.py -q && npm test -- src/admin/UsersPanel.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/admin.py backend/app/api/routes/admin.py backend/tests/api/test_admin.py frontend/src/admin/UsersPanel.tsx frontend/src/admin/UsersPanel.test.tsx
git commit -m "feat: add safe user role and store management"
```

### Task 4: Safe Store Lifecycle

**Files:**
- Modify: `backend/app/api/routes/admin.py`
- Modify: `backend/tests/api/test_admin.py`
- Modify: `frontend/src/admin/StoreSettingsPanel.tsx`
- Create: `frontend/src/admin/StoreSettingsPanel.test.tsx`

**Interfaces:**
- Produces: `DELETE /admin/stores/{store_id}` for unused stores only.
- Uses existing `PATCH is_active=false` for referenced stores.

- [ ] **Step 1: Test delete versus archive**

```py
async def test_referenced_store_cannot_be_deleted(client, admin_headers, store_with_record):
    response = await client.delete(f"/admin/stores/{store_with_record.id}", headers=admin_headers)
    assert response.status_code == 409

async def test_unused_store_can_be_deleted(client, admin_headers, unused_store):
    response = await client.delete(f"/admin/stores/{unused_store.id}", headers=admin_headers)
    assert response.status_code == 204
```

- [ ] **Step 2: Run and verify failure**

Run: `pytest backend/tests/api/test_admin.py -q`
Expected: FAIL because permanent store deletion is not implemented.

- [ ] **Step 3: Implement dependency-count protection**

Count ledger and audit references in the transaction. Return 409 for referenced stores; otherwise delete settings/members/store and audit the deletion before commit.

- [ ] **Step 4: Position page actions correctly**

Render `当前门店` and `新建门店` together in the page header. Keep only `门店名称`, location summary, and save in the form. Place deactivate/delete in the bottom danger area.

- [ ] **Step 5: Run focused tests**

Run: `pytest backend/tests/api/test_admin.py -q && npm test -- src/admin/StoreSettingsPanel.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/admin.py backend/tests/api/test_admin.py frontend/src/admin/StoreSettingsPanel.tsx frontend/src/admin/StoreSettingsPanel.test.tsx
git commit -m "feat: protect referenced stores from deletion"
```

### Task 5: Switchable Map Location Picker

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/maps/types.ts`
- Create: `frontend/src/maps/provider.ts`
- Create: `frontend/src/components/StoreLocationPicker.tsx`
- Create: `frontend/src/components/StoreLocationPicker.test.tsx`
- Modify: `frontend/src/admin/StoreSettingsPanel.tsx`
- Modify: `frontend/src/api/types.ts`
- Modify: `backend/app/services/weather.py`
- Modify: `backend/app/api/routes/admin.py`
- Modify: `backend/tests/api/test_admin.py`

**Interfaces:**
- Produces: `MapLocation { label: string; latitude: number; longitude: number; timezone: string }`
- Produces: `MapAdapter.mount(container, value, onChange): () => void`
- Consumes: `/admin/stores/geocode?query=...`
- Consumes: `/admin/stores/timezone?latitude=...&longitude=...`

- [ ] **Step 1: Install pinned map dependencies**

Run: `npm install leaflet@1.9.4 && npm install -D @types/leaflet@1.9.20`
Expected: package and lock files update successfully.

- [ ] **Step 2: Test that coordinates are absent from the form**

```tsx
expect(screen.queryByLabelText("纬度")).not.toBeInTheDocument();
expect(screen.queryByLabelText("经度")).not.toBeInTheDocument();
await userEvent.click(screen.getByRole("button", { name: "打开地图选择" }));
expect(screen.getByLabelText("搜索城市、区域或地点")).toBeInTheDocument();
```

- [ ] **Step 3: Define the adapter boundary**

```ts
export interface MapLocation { label: string; latitude: number; longitude: number; timezone: string }
export interface MapAdapter {
  mount(container: HTMLElement, value: MapLocation | null, onChange: (value: Pick<MapLocation, "latitude" | "longitude">) => void): () => void;
}
```

- [ ] **Step 4: Implement Leaflet as the default provider**

Create a Leaflet map with configurable tile URL/attribution, a draggable marker, and click-to-move. Keep tile configuration in `provider.ts`, not in `StoreSettingsPanel`.

```ts
export const mapProviderConfig = {
  tiles: import.meta.env.VITE_MAP_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution: "© OpenStreetMap contributors",
};
```

- [ ] **Step 5: Implement search and current location**

Search uses the existing backend geocode route. `navigator.geolocation.getCurrentPosition` centers the map; denial displays `无法获取当前位置，你仍然可以搜索地点`. Confirm returns the selected label/timezone plus internal coordinates.

For device coordinates or a dragged marker, add a backend timezone lookup that calls the configured Open-Meteo provider with `timezone=auto` and returns only `{ "timezone": "Europe/Rome" }`. Keep this provider call behind `OpenMeteoProvider.timezone(latitude, longitude)` so a future AMap/Google adapter can replace it.

- [ ] **Step 6: Run tests and build**

Run: `npm test -- src/components/StoreLocationPicker.test.tsx src/admin/StoreSettingsPanel.test.tsx && npm run build`
Expected: PASS; no visible coordinate inputs.

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/maps frontend/src/components/StoreLocationPicker.tsx frontend/src/components/StoreLocationPicker.test.tsx frontend/src/admin/StoreSettingsPanel.tsx frontend/src/api/types.ts backend/app/services/weather.py backend/app/api/routes/admin.py backend/tests/api/test_admin.py
git commit -m "feat: add switchable map-based store location"
```

### Task 6: Truthful System Status and Final Admin Acceptance

**Files:**
- Modify: `frontend/src/admin/SystemStatusPanel.tsx`
- Create: `frontend/src/admin/SystemStatusPanel.test.tsx`
- Create: `frontend/tests/admin-flow.spec.ts`
- Modify: `frontend/tests/responsive.spec.ts`

**Interfaces:**
- Consumes: existing `/admin/alerts`, `/admin/task-logs`, and dashboard `generated_at` data.

- [ ] **Step 1: Test empty and failure states**

```tsx
it("does not claim healthy when status requests fail", async () => {
  mockStatusFailure();
  renderSystemStatus();
  expect(await screen.findByRole("alert")).toHaveTextContent("状态暂时无法获取");
  expect(screen.queryByText("运行正常")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Implement concise truthful status**

Show last known weather/dashboard timestamps and unresolved alerts. Only render `运行正常` when all required queries succeed and no unresolved error-level alert exists.

- [ ] **Step 3: Add admin browser flow**

```ts
test("admin configures income, user, and mapped store", async ({ page }) => {
  await loginAs(page, "admin");
  await page.goto("/admin");
  await expect(page.getByRole("tab", { name: "收入项目" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "门店设置" }).click();
  await expect(page.getByLabel("纬度")).toHaveCount(0);
  await page.getByRole("button", { name: "打开地图选择" }).click();
});
```

- [ ] **Step 4: Run full verification**

Run: `pytest backend/tests -q && npm test && npm run build && npm run test:e2e`
Expected: all checks PASS, including 320px admin layout.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/SystemStatusPanel.tsx frontend/src/admin/SystemStatusPanel.test.tsx frontend/tests/admin-flow.spec.ts frontend/tests/responsive.spec.ts
git commit -m "test: complete admin and map acceptance flow"
```
