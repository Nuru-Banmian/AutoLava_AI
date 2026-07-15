# Phase 1 Usability 02: Ledger and Income Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix versioned ledger saving and deliver the approved direct-total/composed income modes, calendar date selection, compact form, and ordinary-user mutation limits.

**Architecture:** Use the existing versioned income configuration as the authoritative contract. The frontend loads `/income-config/{store_id}/current`, sends `config_version_id` and `expected_version`, and handles 409 conflicts by refetching instead of exposing technical text. A reusable month calendar drives both ledger and history pages.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, React, TypeScript, TanStack Query, Vitest, Pytest.

## Global Constraints

- Ordinary users may create, backfill, and edit records in assigned stores; only admins may delete or roll back.
- No active income configuration means direct daily-revenue entry.
- Composed mode means item entry only; the backend recomputes the total.
- Dates use the selected store timezone; future dates are disabled.
- Technical config-version fields are never shown to users.

---

### Task 1: Lock the Ledger API Contract

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `backend/tests/api/test_ledger.py`
- Modify: `frontend/src/components/LedgerForm.tsx`
- Modify: `frontend/src/components/LedgerForm.test.tsx`

**Interfaces:**
- Produces: `LedgerBody.daily_revenue`, `config_version_id`, `expected_version`
- Produces: `IncomeConfigResponse` TypeScript interface matching backend schema.

- [ ] **Step 1: Add a backend regression test for the current failure**

```py
async def test_composed_write_requires_and_accepts_current_config_version(client, admin_headers, store, published_config):
    body = ledger_body(items=[{"category_id": published_config.category_id, "amount": "12.00"}])
    body["config_version_id"] = published_config.version_id
    response = await client.put(f"/ledger/{store.id}/2026-07-15", json=body, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["daily_revenue"] == "12.00"
```

- [ ] **Step 2: Run regression tests**

Run: `pytest backend/tests/api/test_ledger.py -q`
Expected: backend contract passes; frontend still lacks fields.

- [ ] **Step 3: Extend TypeScript types exactly**

```ts
export interface IncomeConfigResponse {
  store_id: number;
  version_id: number | null;
  version: number;
  enabled: boolean;
  formula: string;
  items: IncomeConfigItem[];
}
export interface IncomeConfigItem {
  id: number;
  category_id: number | null;
  name: string;
  include_in_total: boolean;
  is_active: boolean;
  sort_order: number;
}
export interface LedgerBody {
  is_open: LedgerStatus;
  daily_revenue: string | null;
  config_version_id: number | null;
  expected_version: number | null;
  wash_count: number | null;
  weather: string | null;
  weather_edited: boolean;
  activity: string | null;
  items: IncomeItemBody[];
}
```

- [ ] **Step 4: Add a frontend form test**

```tsx
expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
  config_version_id: 7,
  expected_version: 3,
  daily_revenue: null,
}));
```

- [ ] **Step 5: Run focused frontend/backend tests**

Run: `pytest backend/tests/api/test_ledger.py -q && npm test -- src/components/LedgerForm.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/api/test_ledger.py frontend/src/api/types.ts frontend/src/components/LedgerForm.tsx frontend/src/components/LedgerForm.test.tsx
git commit -m "fix: bind ledger writes to income config versions"
```

### Task 2: Direct-Total and Composed Form Modes

**Files:**
- Modify: `frontend/src/pages/LedgerPage.tsx`
- Modify: `frontend/src/components/LedgerForm.tsx`
- Modify: `frontend/src/components/LedgerForm.test.tsx`
- Modify: `frontend/src/lib/user-api.ts`

**Interfaces:**
- Produces: `incomeConfigKey(storeId)` and `LedgerFormProps.config`
- Consumes: `/income-config/{store_id}/current`

- [ ] **Step 1: Test both mutually exclusive modes**

```tsx
it("uses direct total when configuration is disabled", async () => {
  renderLedgerForm({ config: { enabled: false, version_id: 4, items: [] } });
  expect(screen.getByLabelText("当日营业额")).toBeEnabled();
  expect(screen.queryByRole("group", { name: "收入项目" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/components/LedgerForm.test.tsx`
Expected: FAIL because direct-total mode does not exist.

- [ ] **Step 3: Load current configuration in LedgerPage**

```ts
export const incomeConfigKey = (storeId: number) => ["income-config", storeId, "current"] as const;
const config = useQuery({
  queryKey: incomeConfigKey(selected.id),
  queryFn: () => api<IncomeConfigResponse>(`/income-config/${selected.id}/current`),
});
```

- [ ] **Step 4: Render one input model only**

```tsx
{config.enabled ? <fieldset aria-label="收入项目">{config.items.filter((item) => item.is_active).map(renderAmount)}</fieldset> :
  <label>当日营业额<Input aria-label="当日营业额" inputMode="decimal" value={directTotal} onChange={(event) => setDirectTotal(event.target.value)} /></label>}
```

On submit, composed mode sends `daily_revenue: null`; direct mode sends canonical `daily_revenue` and `items: []`.

- [ ] **Step 5: Run tests and build**

Run: `npm test -- src/components/LedgerForm.test.tsx src/pages/LedgerPage.test.tsx && npm run build`
Expected: PASS for both modes.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/LedgerPage.tsx frontend/src/components/LedgerForm.tsx frontend/src/components/LedgerForm.test.tsx frontend/src/lib/user-api.ts
git commit -m "feat: support direct and composed ledger income"
```

### Task 3: Shared Store-Timezone Calendar

**Files:**
- Create: `frontend/src/components/MonthCalendar.tsx`
- Create: `frontend/src/components/MonthCalendar.test.tsx`
- Create: `frontend/src/components/LedgerDatePicker.tsx`
- Modify: `frontend/src/pages/LedgerPage.tsx`

**Interfaces:**
- Produces: `MonthCalendar({ month, selected, today, recordedDates, onSelect })`
- Produces: `LedgerDatePicker({ value, today, recordedDates, onChange })`

- [ ] **Step 1: Test dots, selection, and future disabling**

```tsx
it("marks recorded dates and blocks future dates", async () => {
  render(<MonthCalendar month="2026-07" selected="2026-07-15" today="2026-07-15" recordedDates={new Set(["2026-07-14"])} onSelect={onSelect} />);
  expect(screen.getByRole("button", { name: "2026年7月14日，已有记录" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "2026年7月16日" })).toBeDisabled();
});
```

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/components/MonthCalendar.test.tsx`
Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement date generation with `date-fns`**

```tsx
const start = startOfWeek(startOfMonth(parseISO(`${month}-01`)), { weekStartsOn: 1 });
const days = eachDayOfInterval({ start, end: endOfWeek(endOfMonth(parseISO(`${month}-01`)), { weekStartsOn: 1 }) });
return days.map((day) => {
  const iso = format(day, "yyyy-MM-dd");
  const recorded = recordedDates.has(iso);
  return <button aria-label={`${format(day, "yyyy年M月d日")}${recorded ? "，已有记录" : ""}`} disabled={iso > today} onClick={() => onSelect(iso)}>{format(day, "d")}{recorded && <span aria-hidden="true" />}</button>;
});
```

- [ ] **Step 4: Use desktop popover and mobile sheet**

Reuse the existing `Dialog`/`Sheet` primitives. The visible date button opens `LedgerDatePicker`; provide 今天 and 昨天 shortcuts, and display “编辑已有记录” or “补记历史记录” from the record query result.

- [ ] **Step 5: Run tests and build**

Run: `npm test -- src/components/MonthCalendar.test.tsx src/pages/LedgerPage.test.tsx && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/MonthCalendar.tsx frontend/src/components/MonthCalendar.test.tsx frontend/src/components/LedgerDatePicker.tsx frontend/src/pages/LedgerPage.tsx
git commit -m "feat: add store-timezone ledger calendar"
```

### Task 4: Compact Ledger Layout and Conflict Recovery

**Files:**
- Modify: `frontend/src/components/LedgerForm.tsx`
- Modify: `frontend/src/pages/LedgerPage.tsx`
- Modify: `frontend/src/pages/LedgerPage.test.tsx`

**Interfaces:**
- Consumes: `friendlyApiError`, `incomeConfigKey`, `ledgerRecordKey`

- [ ] **Step 1: Test collapsed fields and config conflict recovery**

```tsx
it("refetches config after a version conflict", async () => {
  mockLedgerSave(409, "Income configuration version does not match");
  renderLedgerPage();
  await userEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("收入项目刚刚发生变化");
  expect(mockConfigRequest).toHaveBeenCalledTimes(2);
});
```

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/pages/LedgerPage.test.tsx`
Expected: FAIL because the raw technical message is shown and config is not refetched.

- [ ] **Step 3: Reorder and collapse sections**

Render status, income, computed total, then collapsed `天气` and `洗车数量 / 活动`. Use native buttons with `aria-expanded`; preserve state while collapsed. The main submit label is `保存今日记录`, `保存修改`, or `补记历史记录` according to date/record state.

Register `useBeforeUnload` and a React Router blocker only while the form differs from its loaded snapshot; leaving a clean or successfully saved form must not prompt.

- [ ] **Step 4: Recover from a 409 config conflict**

```ts
if (error instanceof ApiError && error.status === 409 && error.detail.includes("configuration version")) {
  await client.invalidateQueries({ queryKey: incomeConfigKey(storeId), exact: true });
  setMessage(friendlyApiError(error, "保存失败，请重试"));
  return;
}
```

- [ ] **Step 5: Run focused tests and build**

Run: `npm test -- src/pages/LedgerPage.test.tsx src/components/LedgerForm.test.tsx && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/LedgerForm.tsx frontend/src/pages/LedgerPage.tsx frontend/src/pages/LedgerPage.test.tsx
git commit -m "feat: deliver compact conflict-safe ledger"
```

### Task 5: Ordinary-User Delete and Rollback Protection

**Files:**
- Modify: `backend/tests/services/test_access.py`
- Modify: `backend/tests/api/test_database.py`
- Modify: `frontend/src/pages/DatabasePage.tsx`
- Modify: `frontend/src/pages/DatabasePage.test.tsx`

**Interfaces:**
- Preserves backend `ROLE_CAPABILITIES`: user has create/edit but not delete/audit.

- [ ] **Step 1: Add API and UI permission tests**

```py
async def test_regular_user_cannot_delete_or_rollback(client, user_headers, store, record, audit):
    assert (await client.delete(f"/ledger/{store.id}/{record.date}", headers=user_headers)).status_code == 403
    assert (await client.post(f"/database/{store.id}/history/{audit.id}/rollback", headers=user_headers)).status_code == 403
```

```tsx
expect(screen.queryByRole("button", { name: /删除记录/ })).not.toBeInTheDocument();
expect(screen.queryByRole("button", { name: /回滚/ })).not.toBeInTheDocument();
```

- [ ] **Step 2: Run focused permission tests**

Run: `pytest backend/tests/services/test_access.py backend/tests/api/test_database.py -q && npm test -- src/pages/DatabasePage.test.tsx`
Expected: backend passes existing capability rules; frontend test initially fails.

- [ ] **Step 3: Gate dangerous UI by role**

Use `useAuth().user?.role === "admin"` for delete, audit, and rollback controls. Keep edit available for ordinary users. Do not weaken backend dependencies.

- [ ] **Step 4: Run all ledger and permission tests**

Run: `pytest backend/tests/api/test_ledger.py backend/tests/api/test_database.py backend/tests/services/test_access.py -q && npm test -- src/pages/LedgerPage.test.tsx src/pages/DatabasePage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/services/test_access.py backend/tests/api/test_database.py frontend/src/pages/DatabasePage.tsx frontend/src/pages/DatabasePage.test.tsx
git commit -m "fix: enforce regular-user record mutation limits"
```
