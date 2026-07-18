# Custom Date Reveal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide the business-record start and end date controls until the user chooses “自定义”, then keep them expanded until a preset is selected.

**Architecture:** Keep the existing `RecordFiltersProps`, range calculation, export behavior, and `customDraft` state. Add one local visibility state synchronized from `mode`, conditionally render the existing date grid, and protect the behavior with component and responsive browser tests in one self-contained task.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Vitest, Testing Library, Playwright

## Global Constraints

- Preset modes do not render hidden, focusable date inputs.
- `mode === "custom"` always renders the date grid.
- Clicking “自定义” reveals the existing draft and applies it only when it is valid.
- Clicking “本月” or “上月” applies the preset and hides the date grid.
- Valid custom dates update immediately; invalid drafts remain visible and do not call `onChange`.
- Existing 8px row gaps, 4px label gaps, 40px control heights, and `min-w-0` overflow protection remain unchanged.
- No modal, popover, bottom sheet, animation, new dependency, backend change, or change to the analysis-card date filters.

---

### Task 1: Reveal custom business-record dates on demand

**Files:**
- Modify: `frontend/src/components/RecordFilters.tsx`
- Test: `frontend/src/components/RecordFilters.test.tsx`
- Test: `frontend/tests/responsive.spec.ts`

**Interfaces:**
- Consumes: existing `RecordFiltersProps`, `RecordRangeMode`, `DateRange`, and `recordRange()` unchanged.
- Produces: local `customOpen: boolean`; the existing `data-testid="record-filter-dates"` is present only while custom dates are open.

- [ ] **Step 1: Write failing component visibility and transition tests**

Refactor the test setup only enough to reuse standard props, then add assertions equivalent to:

```tsx
const props = {
  mode: "current-month" as const,
  range: { start: "2026-07-01", end: "2026-07-31" },
  today: "2026-07-17",
  exporting: false,
  exportError: "",
  onChange: vi.fn(),
  onExport: vi.fn(),
};

const view = render(<RecordFilters {...props} />);
expect(screen.queryByTestId("record-filter-dates")).not.toBeInTheDocument();

fireEvent.click(screen.getByRole("button", { name: "自定义" }));
expect(screen.getByTestId("record-filter-dates")).toHaveClass("grid", "grid-cols-2");
expect(screen.getByLabelText("开始日期")).toHaveClass("h-10", "min-w-0", "pr-10");
expect(props.onChange).toHaveBeenCalledWith("custom", props.range);

fireEvent.click(screen.getByRole("button", { name: "上月" }));
expect(screen.queryByTestId("record-filter-dates")).not.toBeInTheDocument();
expect(props.onChange).toHaveBeenLastCalledWith("previous-month", {
  start: "2026-06-01",
  end: "2026-06-30",
});

view.rerender(<RecordFilters {...props} mode="custom" />);
expect(screen.getByTestId("record-filter-dates")).toBeInTheDocument();
```

Keep the invalid-range case, but start in preset mode, click “自定义”, enter an invalid draft, and assert that the grid remains mounted while no invalid custom range is emitted.

- [ ] **Step 2: Add failing responsive assertions for the collapsed and expanded states**

In the existing 320px and 390px database tests, scope through the record-filter region. Before clicking “自定义”, assert that record dates are absent:

```ts
const recordFilters = page.getByRole("region", { name: "记录筛选" });
await expect(recordFilters.getByTestId("record-filter-dates")).toHaveCount(0);
await expect(recordFilters.getByLabel("开始日期", { exact: true })).toHaveCount(0);
await expect(recordFilters.getByLabel("结束日期", { exact: true })).toHaveCount(0);
```

After clicking the scoped button, assert the two-column date row, 40px inputs, 8px separation, full-width export row, and existing overflow contract:

```ts
await recordFilters.getByRole("button", { name: "自定义" }).click();
const dates = recordFilters.getByTestId("record-filter-dates");
const exportButton = recordFilters.getByRole("button", { name: "导出当前范围" });
const [filterBox, datesBox, exportBox, startBox, endBox] = await Promise.all([
  recordFilters.boundingBox(),
  dates.boundingBox(),
  exportButton.boundingBox(),
  recordFilters.getByLabel("开始日期", { exact: true }).boundingBox(),
  recordFilters.getByLabel("结束日期", { exact: true }).boundingBox(),
]);
expect(filterBox).not.toBeNull();
expect(datesBox).not.toBeNull();
expect(exportBox).not.toBeNull();
expect(startBox).not.toBeNull();
expect(endBox).not.toBeNull();
expect(startBox!.y).toBe(endBox!.y);
expect(startBox!.height).toBe(40);
expect(endBox!.height).toBe(40);
expect(exportBox!.y).toBeGreaterThanOrEqual(datesBox!.y + datesBox!.height + 8);
expect(exportBox!.width).toBe(filterBox!.width);
```

Keep the existing exact `document.scrollWidth === viewport` assertions at both widths. Keep all analysis-card date assertions unchanged and scope business-record dates through `recordFilters`.

- [ ] **Step 3: Run focused tests and verify the expected failures**

Run each command separately before changing production code:

```powershell
cd frontend
npm test -- RecordFilters.test.tsx
```

Expected: FAIL because `record-filter-dates` still renders in preset mode.

```powershell
cd frontend
npx playwright test tests/responsive.spec.ts
```

Expected: FAIL at the new collapsed-state assertion because the record date grid is still present before “自定义”. Existing unrelated responsive assertions remain green.

- [ ] **Step 4: Implement the minimal local visibility state**

In `RecordFilters.tsx`, add state and synchronize it with external mode and range updates:

```tsx
const [customDraft, setCustomDraft] = useState<DateRange>(range);
const [customOpen, setCustomOpen] = useState(mode === "custom");

useEffect(() => {
  setCustomDraft(range);
  setCustomOpen(mode === "custom");
}, [mode, range]);
```

Make preset selection close the dates before applying the existing range:

```tsx
const choosePreset = (next: Exclude<RecordRangeMode, "custom">) => {
  setCustomOpen(false);
  onChange(next, recordRange(next, today));
};
```

Make the custom button reveal the grid before optionally applying a valid draft:

```tsx
onClick={() => {
  setCustomOpen(true);
  if (customRangeIsValid(customDraft)) onChange("custom", customDraft);
}}
```

Conditionally render the existing date grid without changing its classes or children:

```tsx
{customOpen && (
  <div className="grid grid-cols-2 gap-2" data-testid="record-filter-dates">
    <label className="grid min-w-0 gap-1 text-sm">开始日期
      <NativeDateInput aria-label="开始日期" max={today} value={customDraft.start} onChange={(event) => updateCustom({ start: event.target.value })} />
    </label>
    <label className="grid min-w-0 gap-1 text-sm">结束日期
      <NativeDateInput aria-label="结束日期" max={today} value={customDraft.end} onChange={(event) => updateCustom({ end: event.target.value })} />
    </label>
  </div>
)}
```

- [ ] **Step 5: Run focused component and browser checks**

Run:

```powershell
cd frontend
npm test -- RecordFilters.test.tsx NativeDateInput.test.tsx
```

Expected: both files pass; invalid ranges do not emit changes and the 40px native date contracts remain intact.

Run:

```powershell
cd frontend
npx playwright test tests/responsive.spec.ts
```

Expected: all responsive scenarios pass at desktop, 390px, and 320px with no horizontal overflow.

If a browser failure reproduces a real product defect, invoke `superpowers:systematic-debugging`, preserve the failing assertion, and fix only the confirmed root cause.

- [ ] **Step 6: Run the feature-group quality gate**

Run each command separately:

```powershell
cd frontend
npm test
```

Expected: all Vitest files pass.

```powershell
cd frontend
npm run build
```

Expected: exit 0; the existing bundle-size warning may remain.

- [ ] **Step 7: Commit the completed behavior and coverage**

```powershell
git add frontend/src/components/RecordFilters.tsx frontend/src/components/RecordFilters.test.tsx frontend/tests/responsive.spec.ts
git commit -m "feat: reveal custom record dates on demand"
```
