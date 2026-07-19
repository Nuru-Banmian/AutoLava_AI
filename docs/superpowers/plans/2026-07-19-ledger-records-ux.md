# Ledger and Business Records UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Streamline daily ledger weather and amount entry, preserve the Business Records workspace across edits, remove the redundant delete-management step, and conditionally show categorized income analysis.

**Architecture:** Keep the backend contract unchanged. Implement form behavior at `LedgerForm`, carry a typed return snapshot through React Router navigation state, and make analysis composition rendering depend on the category rows already returned by the charts endpoint.

**Tech Stack:** React, TypeScript, React Router, TanStack Query, Radix Select, Vitest, Testing Library, MSW.

## Global Constraints

- Record weather is empty or one of exactly `晴`, `多云`, `雾`, `雨`, `雪`, `雷雨`.
- Empty automatic weather must never block saving a ledger record.
- New `营业` and `天气停业` amounts start empty; saved values, including zero, remain visible.
- `休息` continues to save zero amounts and wash count.
- Only saves launched from Business Records return to Business Records.
- Delete remains administrator-only and always requires final confirmation.
- Do not add or change backend endpoints.

---

### Task 1: Ledger weather and empty new-record amounts

**Files:**
- Modify: `frontend/src/components/LedgerForm.tsx`
- Modify: `frontend/src/components/LedgerForm.test.tsx`
- Modify: `frontend/src/pages/LedgerPage.test.tsx`
- Modify: `CONTEXT.md`

**Interfaces:**
- Consumes: existing `LedgerFormProps`, `LedgerBody`, and automatic `WeatherResponse`.
- Produces: the same `onSave(body: LedgerBody)` contract; visible weather is a six-value select with an empty placeholder.

- [ ] **Step 1: Write the failing weather-select test**

```tsx
it("offers only the six record-weather choices and can save before weather is known", async () => {
  const onSave = vi.fn();
  render(<LedgerForm categories={[]} config={directConfig} onSave={onSave} />);
  const user = userEvent.setup();
  expect(screen.getByRole("combobox", { name: "天气" })).toHaveTextContent("请选择天气");
  await user.click(screen.getByRole("combobox", { name: "天气" }));
  expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(["晴", "多云", "雾", "雨", "雪", "雷雨"]);
  await user.keyboard("{Escape}");
  fireEvent.change(screen.getByLabelText("当日营业额"), { target: { value: "12" } });
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ weather: null }));
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `cd frontend; npm test -- src/components/LedgerForm.test.tsx`

Expected: FAIL because weather is still a collapsed free-text input.

- [ ] **Step 3: Replace the weather accordion with the existing Radix select primitives**

```tsx
const RECORD_WEATHER_OPTIONS = ["晴", "多云", "雾", "雨", "雪", "雷雨"] as const;

<label className="grid gap-1">天气
  <Select value={weatherValue || undefined} onValueChange={(value) => {
    setWeatherValue(value);
    setWeatherEdited(true);
  }}>
    <SelectTrigger aria-label="天气"><SelectValue placeholder="请选择天气" /></SelectTrigger>
    <SelectContent>{RECORD_WEATHER_OPTIONS.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
  </Select>
</label>
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `cd frontend; npm test -- src/components/LedgerForm.test.tsx`

Expected: PASS.

- [ ] **Step 5: Write the failing empty-amount test**

```tsx
it("starts new business amounts empty while preserving saved zeroes and rest normalization", () => {
  const view = render(<LedgerForm categories={[]} config={composedConfig} onSave={vi.fn()} />);
  expect(screen.getByLabelText("现金")).toHaveValue("");
  expect(screen.getByLabelText("不计入")).toHaveValue("");
  const zeroRecord = savedRecord({ daily_revenue: 0, items: [{ ...savedRecord().items[0], amount: 0 }] });
  view.rerender(<LedgerForm categories={[]} config={composedConfig} record={zeroRecord} onSave={vi.fn()} />);
  expect(screen.getByLabelText("历史现金")).toHaveValue("0");
});
```

- [ ] **Step 6: Run the focused test and verify it fails**

Run: `cd frontend; npm test -- src/components/LedgerForm.test.tsx`

Expected: FAIL because new category amounts and direct totals currently start at `0`.

- [ ] **Step 7: Initialize only new business amounts as empty**

```tsx
const loadedAmounts = useMemo(() => Object.fromEntries(active.map((category) => [
  category.id,
  record ? String(record.items.find((item) => item.category_id === category.id)?.amount ?? 0) : "",
])), [active, record]);
const [directTotal, setDirectTotal] = useState(record ? String(record.daily_revenue) : "");
```

- [ ] **Step 8: Run focused tests and typecheck**

Run: `cd frontend; npm test -- src/components/LedgerForm.test.tsx src/pages/LedgerPage.test.tsx; npx tsc -b --pretty false`

Expected: PASS and exit code 0.

- [ ] **Step 9: Commit the ledger form slice**

```powershell
git add CONTEXT.md docs/superpowers/plans/2026-07-19-ledger-records-ux.md frontend/src/components/LedgerForm.tsx frontend/src/components/LedgerForm.test.tsx frontend/src/pages/LedgerPage.test.tsx
git commit -m "feat: streamline daily ledger entry"
```

### Task 2: Return to the exact Business Records workspace after save

**Files:**
- Create: `frontend/src/navigation/business-records-return.ts`
- Modify: `frontend/src/pages/BusinessRecordsPage.tsx`
- Modify: `frontend/src/pages/LedgerPage.tsx`
- Modify: `frontend/src/components/RecordDetailPanel.tsx`
- Modify: `frontend/src/components/MobileRecordSheet.tsx`
- Modify: `frontend/src/components/BusinessAnalysisCard.tsx`
- Modify: `frontend/src/pages/BusinessRecordsPage.test.tsx`
- Modify: `frontend/src/pages/LedgerPage.test.tsx`

**Interfaces:**
- Produces: `BusinessRecordsViewState`, `LedgerLocationState`, and `BusinessRecordsLocationState` as typed React Router state.
- Consumes: `navigate("/ledger?...", { state })` on edit and `navigate("/database", { replace: true, state })` after successful save.

- [ ] **Step 1: Write a failing routed workflow test**

```tsx
it("returns after a successful records-launched save and restores the workspace", async () => {
  const router = createMemoryRouter([
    { path: "/database", element: <BusinessRecordsPage /> },
    { path: "/ledger", element: <LedgerPage /> },
  ], { initialEntries: ["/database"] });
  render(<QueryClientProvider client={client}><StoreProvider><UnsavedChangesProvider><RouterProvider router={router} /></UnsavedChangesProvider></StoreProvider></QueryClientProvider>);
  fireEvent.click(within(screen.getByLabelText("记录筛选")).getByRole("button", { name: "上月" }));
  fireEvent.click(await screen.findByRole("link", { name: "修改这天记录" }));
  fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "25" } });
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  expect(await screen.findByRole("heading", { name: "营业记录" })).toBeInTheDocument();
  expect(within(screen.getByLabelText("记录筛选")).getByRole("button", { name: "上月" })).toHaveAttribute("aria-pressed", "true");
});
```

- [ ] **Step 2: Run the workflow test and verify it fails**

Run: `cd frontend; npm test -- src/pages/BusinessRecordsPage.test.tsx src/pages/LedgerPage.test.tsx`

Expected: FAIL because edit links carry only the date and successful saves do not navigate.

- [ ] **Step 3: Add the typed return snapshot**

```ts
export interface BusinessAnalysisViewState {
  mode: AnalysisRangeMode;
  custom: DateRange;
}

export interface BusinessRecordsViewState {
  storeId: number;
  recordMode: RecordRangeMode;
  range: DateRange;
  page: number;
  selectedDate: string | null;
  mobileRecordDate: string | null;
  analysis: BusinessAnalysisViewState;
  scrollY: number;
}
```

- [ ] **Step 4: Navigate from record details with a click-time snapshot**

```tsx
const editRecord = (date: string) => navigate(`/ledger?date=${date}`, {
  state: { returnToBusinessRecords: {
    storeId: selected.id,
    recordMode,
    range,
    page,
    selectedDate,
    mobileRecordDate: mobileRecord?.date ?? null,
    analysis,
    scrollY: window.scrollY,
  } },
});
```

Keep the edit control as a link with its real `href`, prevent its default click, and call the parent handler so keyboard and pointer activation share the same behavior.

- [ ] **Step 5: Restore state and consume the restore payload**

Initialize Business Records range, page, selected date, mobile detail date, and analysis state from `location.state.restoreBusinessRecords` when its `storeId` matches the selected store. Restore `scrollY` after render, then replace the history entry with null state so a later unrelated visit does not replay it.

- [ ] **Step 6: Return only after a successful origin-aware save**

```tsx
await invalidateUserData(client, variables.storeId);
if (returnToBusinessRecords && returnToBusinessRecords.storeId === variables.storeId) {
  resetUnsavedChanges();
  navigate("/database", { replace: true, state: { restoreBusinessRecords: returnToBusinessRecords } });
}
```

- [ ] **Step 7: Run focused tests and typecheck**

Run: `cd frontend; npm test -- src/pages/BusinessRecordsPage.test.tsx src/pages/LedgerPage.test.tsx; npx tsc -b --pretty false`

Expected: PASS and exit code 0, including a direct-ledger save test that remains on `/ledger`.

- [ ] **Step 8: Commit the return-flow slice**

```powershell
git add frontend/src/navigation/business-records-return.ts frontend/src/pages/BusinessRecordsPage.tsx frontend/src/pages/LedgerPage.tsx frontend/src/components/RecordDetailPanel.tsx frontend/src/components/MobileRecordSheet.tsx frontend/src/components/BusinessAnalysisCard.tsx frontend/src/pages/BusinessRecordsPage.test.tsx frontend/src/pages/LedgerPage.test.tsx
git commit -m "feat: restore business records after ledger edits"
```

### Task 3: Direct delete confirmation

**Files:**
- Create: `frontend/src/components/DeleteRecordDialog.tsx`
- Create: `frontend/src/components/DeleteRecordDialog.test.tsx`
- Delete: `frontend/src/components/RecordManagementDialogs.tsx`
- Delete: `frontend/src/components/RecordManagementDialogs.test.tsx`
- Modify: `frontend/src/components/RecordDetailPanel.tsx`
- Modify: `frontend/src/components/RecordDetailPanel.test.tsx`
- Modify: `frontend/src/components/MobileRecordSheet.tsx`
- Modify: `frontend/src/pages/BusinessRecordsPage.tsx`
- Modify: `frontend/src/pages/BusinessRecordsPage.test.tsx`

**Interfaces:**
- Produces: administrator-only `删除这天记录` action and one controlled `DeleteRecordDialog` confirmation.
- Consumes: unchanged `DELETE /api/ledger/{storeId}/{date}` endpoint.

- [ ] **Step 1: Write the failing direct-confirmation test**

```tsx
it("opens final delete confirmation directly from the record detail", async () => {
  fireEvent.click(screen.getByRole("button", { name: "删除这天记录" }));
  expect(await screen.findByRole("heading", { name: "确认永久删除记录？" })).toBeInTheDocument();
  expect(screen.queryByText(/管理 .* 记录/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `cd frontend; npm test -- src/pages/BusinessRecordsPage.test.tsx`

Expected: FAIL because the visible action is `管理这天记录` and opens an intermediate dialog.

- [ ] **Step 3: Replace management controls with the controlled delete confirmation**

`RecordDetailPanel` exposes `canDelete` and `onDelete`; its destructive button opens `DeleteRecordDialog` directly. Keep the existing mutation, cache invalidation, conflict error, success message, and `onCompleted` behavior.

- [ ] **Step 4: Run focused tests and typecheck**

Run: `cd frontend; npm test -- src/components/DeleteRecordDialog.test.tsx src/components/RecordDetailPanel.test.tsx src/pages/BusinessRecordsPage.test.tsx; npx tsc -b --pretty false`

Expected: PASS and exit code 0.

- [ ] **Step 5: Commit the delete-flow slice**

```powershell
git add -A frontend/src/components frontend/src/pages/BusinessRecordsPage.tsx frontend/src/pages/BusinessRecordsPage.test.tsx
git commit -m "feat: open record deletion confirmation directly"
```

### Task 4: Conditional income composition

**Files:**
- Modify: `frontend/src/components/BusinessAnalysisCard.tsx`
- Modify: `frontend/src/components/BusinessAnalysisCard.test.tsx`
- Modify: `frontend/src/components/IncomeComposition.tsx`
- Modify: `frontend/src/components/IncomeComposition.test.tsx`

**Interfaces:**
- Consumes: existing `ChartsResponse.categories` and `ChartsResponse.excluded_categories`.
- Produces: no composition for total-only ranges; `收入分类` for categorized ranges; `其他数据` only when excluded rows exist.

- [ ] **Step 1: Write a failing total-only visibility test**

```tsx
it("hides income composition when the selected range has no categorized rows", async () => {
  server.use(http.get("/api/charts/1", () => HttpResponse.json(payload({
    categories: [],
    excluded_categories: [],
    kpis: { ...payload().kpis, total_revenue: 100 },
  }))));
  renderCard();
  await screen.findByText("营业额趋势");
  expect(screen.queryByRole("region", { name: "收入构成" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `cd frontend; npm test -- src/components/BusinessAnalysisCard.test.tsx`

Expected: FAIL because `IncomeComposition` always renders.

- [ ] **Step 3: Render composition only when either category group has rows**

```tsx
const hasCategorizedData = data.categories.length > 0 || data.excluded_categories.length > 0;
{hasCategorizedData && <IncomeComposition {...compositionProps} />}
```

- [ ] **Step 4: Write the failing Other Data visibility and copy test**

```tsx
expect(screen.getByRole("region", { name: "其他数据" })).toBeInTheDocument();
expect(screen.queryByText(/不会计入|历史总额记录/)).not.toBeInTheDocument();
```

- [ ] **Step 5: Rename and conditionally render the excluded group**

Render the second `CompositionGroup` and separator only when `excluded.length > 0`, use title and expansion copy `其他数据`, and remove both explanatory paragraphs.

- [ ] **Step 6: Run focused tests and typecheck**

Run: `cd frontend; npm test -- src/components/BusinessAnalysisCard.test.tsx src/components/IncomeComposition.test.tsx; npx tsc -b --pretty false`

Expected: PASS and exit code 0.

- [ ] **Step 7: Commit the analysis slice**

```powershell
git add frontend/src/components/BusinessAnalysisCard.tsx frontend/src/components/BusinessAnalysisCard.test.tsx frontend/src/components/IncomeComposition.tsx frontend/src/components/IncomeComposition.test.tsx
git commit -m "feat: simplify categorized income analysis"
```

### Task 5: Full verification and review

**Files:**
- Modify only files required by failures or review findings.

**Interfaces:**
- Consumes: all four completed frontend slices.
- Produces: a green frontend suite and production build.

- [ ] **Step 1: Run the complete frontend suite**

Run: `cd frontend; npm test`

Expected: all tests pass.

- [ ] **Step 2: Run the production build**

Run: `cd frontend; npm run build`

Expected: TypeScript and Vite build exit successfully.

- [ ] **Step 3: Review the committed diff from fixed point `098831e7e7195b1b734a63be2f49700c46582e5c`**

Run Standards and Spec review agents against:

```powershell
git diff 098831e7e7195b1b734a63be2f49700c46582e5c...HEAD
git log 098831e7e7195b1b734a63be2f49700c46582e5c..HEAD --oneline
```

- [ ] **Step 4: Fix every accepted review finding and re-run affected tests plus the full suite/build**

Use one red-green cycle for any behavior correction. Commit review fixes with a descriptive message; if there are no findings, no extra commit is required.
