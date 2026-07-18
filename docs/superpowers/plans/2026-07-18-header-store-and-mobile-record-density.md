# 全局门店入口与移动营业记录密度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the global store selector into the desktop/mobile shell header, compact mobile business-record controls and rows, and finish with targeted admin interaction regression checks.

**Architecture:** `AppShell` owns route-aware placement and visibility of the global store context; `StorePicker` owns its shared 40px control contract. `RecordFilters` owns responsive filter composition, `NativeDateInput` owns shared date sizing, and `MobileRecordList` owns row density. Admin verification reuses existing unit and Playwright flows after layout work is complete.

**Tech Stack:** React, TypeScript, React Router, Tailwind CSS, Vitest, React Testing Library, Playwright.

## Global Constraints

- Desktop global store selector appears below AutoLava AI in the fixed left sidebar.
- Mobile global store selector appears at the right of the same top row as AutoLava AI.
- Remove the store selector from More; render only one visible global selector per viewport.
- Hide the global selector and its store-load error/retry notice throughout `/admin`; restore both after leaving without losing selected-store state.
- Store selector, date input, calendar trigger, preset buttons, and export button use a shared 40px height.
- At mobile widths, presets are one three-column row, dates are one two-column row, and export is one full-width row with 8px row gaps and 4px label gaps.
- Compact only mobile record-row vertical whitespace; preserve content, order, selection, sheet behavior, and accessible names.
- Long store names must not push the brand, overlap navigation, or create horizontal overflow.
- Preserve StoreProvider data flow, date validation, export behavior, error handling, and keyboard accessibility.
- Use focused tests while implementing; run the full frontend suite/build and targeted Playwright only after the feature group.

---

## File Structure

- Modify: `frontend/src/layouts/AppShell.tsx` — route-aware global selector placement and admin exception.
- Modify: `frontend/src/components/StorePicker.tsx` — shared 40px selector and optional visually hidden label.
- Modify: `frontend/src/pages/MorePage.tsx` — remove duplicate selector.
- Modify: `frontend/src/App.test.tsx` — shell placement, More removal, admin hide/restore, long-name contracts.
- Modify: `frontend/src/components/RecordFilters.tsx` — responsive three-layer mobile filter grid.
- Modify: `frontend/src/components/RecordFilters.test.tsx` — mobile layout and 40px controls.
- Modify: `frontend/src/components/NativeDateInput.tsx` — 40px input and calendar trigger.
- Modify: `frontend/src/components/NativeDateInput.test.tsx` — updated shared size and picker behavior.
- Modify: `frontend/src/components/MobileRecordList.tsx` — compact row padding.
- Modify: `frontend/src/components/MobileRecordList.test.tsx` — density contract and interaction preservation.
- Modify: `frontend/tests/responsive.spec.ts` — real desktop/mobile shell and record-filter geometry.
- Modify: `frontend/tests/admin-flow.spec.ts` — final admin shell/interaction regression.

### Task 1: Route-aware global store selector

**Files:**
- Modify: `frontend/src/layouts/AppShell.tsx`
- Modify: `frontend/src/components/StorePicker.tsx`
- Modify: `frontend/src/pages/MorePage.tsx`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: `StorePicker({ showLabel?: boolean }): JSX.Element`, defaulting `showLabel` to `true`.
- Consumes: `useLocation().pathname` to derive `const isAdminRoute = pathname === "/admin" || pathname.startsWith("/admin/")`.
- Preserves: current `useStore()` selection and error/refetch APIs.

- [ ] **Step 1: Write failing shell tests**

Update `App.test.tsx` to return at least two accessible stores from the default handler. Change `renderApplication` so the router is available for route-transition assertions:

```tsx
function renderApplication(path: string, options: { role?: "admin" | "user" } = {}) {
  if (options.role) {
    server.use(http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: options.role, role: options.role, is_owner: false })));
  }
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createAppRouter([path]);
  return { ...render(<Application queryClient={queryClient} router={router} />), router };
}
```

Then add these assertions:

```tsx
it("moves the global store selector out of More and into the shell", async () => {
  renderApplication("/more", { role: "user" });
  const more = await screen.findByRole("navigation", { name: "更多功能" });
  expect(within(more).queryByRole("combobox", { name: "门店" })).not.toBeInTheDocument();
  expect(screen.getAllByRole("combobox", { name: "门店" })).toHaveLength(2);
});

it("hides global store context in admin and restores it after leaving", async () => {
  const view = renderApplication("/admin", { role: "admin" });
  await screen.findByRole("heading", { name: "系统管理" });
  expect(screen.queryByRole("combobox", { name: "门店" })).not.toBeInTheDocument();
  expect(screen.queryByText("门店加载失败，请重试")).not.toBeInTheDocument();
  await view.router.navigate("/");
  expect(await screen.findAllByRole("combobox", { name: "门店" })).toHaveLength(2);
});
```

Add shell wrapper test ids and assert the desktop picker wrapper is ordered after the brand and the mobile picker wrapper is in the same header row. Update the long-name test to inspect the shell picker rather than the removed More card.

- [ ] **Step 2: Run the focused test and verify failure**

```powershell
cd frontend
npm test -- App.test.tsx
```

Expected: FAIL because More still contains the selector, AppShell lacks top selectors, and `/admin` still exposes global store context.

- [ ] **Step 3: Implement route-aware shell placement**

In `StorePicker.tsx`, add the optional label presentation and 40px select:

```tsx
export function StorePicker({ showLabel = true }: { showLabel?: boolean }) {
  const { stores, selected, select, isLoading, error } = useStore();
  return <div className="min-w-0 max-w-full">
    <label className="flex min-w-0 max-w-full items-center gap-2">
      <span className={showLabel ? "shrink-0" : "sr-only"}>门店</span>
      <select
        aria-label="门店"
        className="h-10 min-w-0 max-w-full flex-1 truncate rounded border px-2 text-sm"
        value={selected?.id ?? ""}
        disabled={isLoading || Boolean(error) || !stores.length}
        onChange={(event) => select(Number(event.target.value))}
      >
        <option value="">请选择门店</option>
        {stores.map((store) => <option key={store.id} value={store.id}>{store.name}{store.is_active === false ? "（已归档）" : ""}</option>)}
      </select>
    </label>
  </div>;
}
```

Retain the existing “请先选择门店” status paragraph.

In `AppShell.tsx`, import `useLocation`, calculate `isAdminRoute`, and:

- place a desktop `StorePicker` under the brand area in the sidebar before navigation;
- place `<StorePicker showLabel={false} />` in a right-aligned, width-capped mobile header wrapper;
- wrap both selector surfaces in `!isAdminRoute`;
- wrap the global `storeError` alert in `!isAdminRoute`;
- remove the bottom-sidebar `StorePicker` while retaining username/logout;
- use `data-testid="desktop-store-picker"` and `data-testid="mobile-store-picker"` wrappers.

In `MorePage.tsx`, remove the `StorePicker` import and its card.

- [ ] **Step 4: Run the focused test and verify pass**

```powershell
cd frontend
npm test -- App.test.tsx
```

Expected: PASS, including admin hide/restore and long-name structural assertions.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/layouts/AppShell.tsx frontend/src/components/StorePicker.tsx frontend/src/pages/MorePage.tsx frontend/src/App.test.tsx
git commit -m "feat: move global store selector into app shell"
```

### Task 2: Compact responsive business-record filters

**Files:**
- Modify: `frontend/src/components/RecordFilters.tsx`
- Modify: `frontend/src/components/RecordFilters.test.tsx`
- Modify: `frontend/src/components/NativeDateInput.tsx`
- Modify: `frontend/src/components/NativeDateInput.test.tsx`

**Interfaces:**
- Consumes: existing `RecordFiltersProps` and `NativeDateInput` props unchanged.
- Produces: mobile grid contract with `grid-cols-3`, `grid-cols-2`, and full-width export.
- Produces: 40px date input and calendar-trigger contract via `h-10` and `size-10`.

- [ ] **Step 1: Write failing filter and date-size tests**

In `RecordFilters.test.tsx`, assert the three layout groups and control sizing:

```tsx
expect(screen.getByLabelText("日期范围预设")).toHaveClass("grid", "grid-cols-3");
expect(screen.getByTestId("record-filter-dates")).toHaveClass("grid", "grid-cols-2");
for (const name of ["本月", "上月", "自定义", "导出当前范围"]) {
  expect(screen.getByRole("button", { name })).toHaveClass("h-10");
}
expect(screen.getByRole("button", { name: "导出当前范围" })).toHaveClass("w-full");
```

In `NativeDateInput.test.tsx`, replace 44px assertions with:

```tsx
expect(screen.getByLabelText("开始日期")).toHaveClass("h-10", "pr-10");
expect(screen.getByRole("button", { name: "打开开始日期日历" })).toHaveClass("size-10");
```

Keep `showPicker()` and focus fallback tests unchanged.

- [ ] **Step 2: Run focused tests and verify failure**

```powershell
cd frontend
npm test -- RecordFilters.test.tsx NativeDateInput.test.tsx
```

Expected: FAIL because controls remain 44px and filters remain one wrapping flex row.

- [ ] **Step 3: Implement the responsive grid and 40px controls**

Refactor `RecordFilters.tsx` to this structure while preserving all handlers and error rendering:

```tsx
<section aria-label="记录筛选" className="grid gap-2 md:flex md:flex-wrap md:items-end">
  <div className="grid grid-cols-3 gap-2 md:flex" aria-label="日期范围预设">
    {/* existing preset and custom buttons, each class uses h-10 w-full md:w-auto */}
  </div>
  <div className="grid grid-cols-2 gap-2" data-testid="record-filter-dates">
    {/* existing labels, each grid gap-1 text-sm */}
  </div>
  <button className="h-10 w-full ... md:w-auto">{/* existing export */}</button>
  {/* existing error */}
</section>
```

Change preset/custom button classes from `min-h-11` to `h-10 w-full md:w-auto`.

In `NativeDateInput.tsx`, change the input to `h-10 pr-10` and the trigger to `size-10`; retain native `type="date"`, hidden built-in indicator, picker behavior, and accessible button name.

- [ ] **Step 4: Run focused tests and verify pass**

```powershell
cd frontend
npm test -- RecordFilters.test.tsx NativeDateInput.test.tsx
```

Expected: PASS with existing range and export behavior unchanged.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/RecordFilters.tsx frontend/src/components/RecordFilters.test.tsx frontend/src/components/NativeDateInput.tsx frontend/src/components/NativeDateInput.test.tsx
git commit -m "feat: compact mobile record filters"
```

### Task 3: Compact mobile record rows

**Files:**
- Modify: `frontend/src/components/MobileRecordList.tsx`
- Modify: `frontend/src/components/MobileRecordList.test.tsx`

**Interfaces:**
- Consumes: existing `MobileRecordListProps`.
- Produces: unchanged record trigger semantics with `py-2` vertical density.

- [ ] **Step 1: Write the failing density and interaction test**

Extend `MobileRecordList.test.tsx`:

```tsx
const onSelect = vi.fn();
render(<MobileRecordList records={[record]} selectedDate={record.date} onSelect={onSelect} />);
const row = screen.getByRole("button", { name: /2026年7月14日，休息，€100.00/ });
expect(row).toHaveClass("py-2");
expect(row).not.toHaveClass("py-3");
expect(row).toHaveAttribute("aria-pressed", "true");
row.click();
expect(onSelect).toHaveBeenCalledWith(record, row);
```

Retain assertions that weather, activity, and wash count are not added.

- [ ] **Step 2: Run the focused test and verify failure**

```powershell
cd frontend
npm test -- MobileRecordList.test.tsx
```

Expected: FAIL because the row still uses `py-3`.

- [ ] **Step 3: Apply the minimal density change**

In `MobileRecordList.tsx`, change only the row class from `py-3` to `py-2`:

```tsx
className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 overflow-hidden px-3 py-2 text-left aria-pressed:bg-primary/10"
```

Do not change columns, data, order, callback, labels, or sheet integration.

- [ ] **Step 4: Run the focused test and verify pass**

```powershell
cd frontend
npm test -- MobileRecordList.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/MobileRecordList.tsx frontend/src/components/MobileRecordList.test.tsx
git commit -m "style: compact mobile record rows"
```

### Task 4: Browser acceptance and final admin interaction audit

**Files:**
- Modify: `frontend/tests/responsive.spec.ts`
- Modify: `frontend/tests/admin-flow.spec.ts`
- Modify only if a reproducible bug is found: the exact production file responsible for that bug plus its nearest focused test.

**Interfaces:**
- Consumes: completed Tasks 1–3.
- Produces: browser evidence for responsive layout and admin isolation.
- Debug contract: any failure invokes `superpowers:systematic-debugging`; a production fix requires a failing regression test before implementation.

- [ ] **Step 1: Add failing responsive browser assertions**

Extend the authenticated responsive API fixture and tests to assert:

```ts
await page.setViewportSize({ width: 390, height: 844 });
await page.goto("/database");
await expect(page.getByTestId("mobile-store-picker").getByRole("combobox", { name: "门店" })).toBeVisible();
await expect(page.getByTestId("desktop-store-picker")).toBeHidden();
await expect(page.getByLabel("日期范围预设").getByRole("button")).toHaveCount(3);
for (const control of await page.getByLabel("日期范围预设").getByRole("button").all()) {
  expect((await control.boundingBox())?.height).toBe(40);
}
expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
```

At desktop width, assert the desktop picker is visible below the brand and the mobile picker hidden. Add a long store name fixture and assert the header width does not exceed its viewport.

- [ ] **Step 2: Extend the admin browser flow before running it**

In `admin-flow.spec.ts`, after `page.goto("/admin")` add:

```ts
await expect(page.getByRole("combobox", { name: "门店" })).toHaveCount(0);
await expect(page.getByText("门店加载失败，请重试")).toHaveCount(0);
await page.getByRole("tab", { name: "用户与权限" }).click();
await expect(page).toHaveURL(/\/admin\?tab=users$/);
await page.getByRole("tab", { name: "系统状态" }).click();
await expect(page).toHaveURL(/\/admin\?tab=status$/);
await expect(page.getByText("运行状态")).toBeVisible();
await page.getByRole("tab", { name: "门店与收入" }).click();
```

Keep the existing income, user, and mapped-store creation path. Add one route-away assertion at the end: navigate to `/`, verify the global store combobox is visible and its selected option remains Roma.

- [ ] **Step 3: Run focused component and browser checks**

```powershell
cd frontend
npm test -- App.test.tsx RecordFilters.test.tsx NativeDateInput.test.tsx MobileRecordList.test.tsx AdminPage.test.tsx StoreWorkspace.test.tsx UsersPanel.test.tsx SystemStatusPanel.test.tsx
npx playwright test tests/responsive.spec.ts tests/admin-flow.spec.ts
```

Expected: all focused tests pass. If any failure occurs, record its exact reproduction and invoke `superpowers:systematic-debugging` before modifying production code. Add the smallest failing regression test, fix the confirmed root cause, then rerun the directly affected command.

- [ ] **Step 4: Run the feature-group quality gate**

```powershell
cd frontend
npm test
npm run build
npm run test:e2e
```

Expected: all commands exit 0. Existing non-failing bundle-size warnings may remain documented; new warnings or errors are defects.

- [ ] **Step 5: Commit browser coverage or confirmed fixes**

```powershell
git add frontend/tests/responsive.spec.ts frontend/tests/admin-flow.spec.ts
git commit -m "test: verify shell and admin store interactions"
```

If systematic debugging produced a confirmed fix, include only its production file and regression test in the same commit after all covering checks pass.
