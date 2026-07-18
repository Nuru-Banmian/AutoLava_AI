# 营业记录分析布局与日期控件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve desktop trend-chart readability and make all business-record date inputs easy to tap without changing date-range behavior.

**Architecture:** Extract the shared visual contract for native date inputs into one small component, then use it in record filters and custom analysis ranges. Keep `ChartPanel` responsive by adding an optional height-class override; only the embedded revenue trend opts into the compact height. The business-record page owns desktop column allocation.

**Tech Stack:** React, TypeScript, Tailwind CSS, Vitest, React Testing Library, Recharts.

## Global Constraints

- Keep `type="date"`, existing accessible names, browser-native calendar behavior, and all min/max validation unchanged.
- All four relevant date inputs must have at least `44px` height and a `44px` calendar-trigger area.
- At `lg` and above, the analysis sidebar must be `30–32rem`; below `lg`, retain the existing single-column flow.
- The embedded revenue trend must be `16rem` high; other charts retain their current `18rem` height.
- Do not change APIs, date-range calculation, export behavior, requests, or mobile ordering.
- Follow the repository rapid workflow: focused frontend tests during tasks; run the frontend suite and production build only before the next PR update.

---

## File Structure

- Create: `frontend/src/components/NativeDateInput.tsx` — shared accessible native-date input with the 44px visual/touch contract.
- Create: `frontend/src/components/NativeDateInput.test.tsx` — unit test for shared sizing and pass-through constraints.
- Modify: `frontend/src/components/RecordFilters.tsx` and `frontend/src/components/BusinessAnalysisCard.tsx` — use the shared date input in all four locations.
- Modify: `frontend/src/components/ChartPanel.tsx` — support an optional chart-height class without changing the default.
- Modify: `frontend/src/pages/BusinessRecordsPage.tsx` — assign the approved desktop analysis-column width.
- Modify: respective component and page tests — assert layout and accessibility contracts.

### Task 1: Shared native date-input contract

**Files:**
- Create: `frontend/src/components/NativeDateInput.tsx`
- Create: `frontend/src/components/NativeDateInput.test.tsx`
- Modify: `frontend/src/components/RecordFilters.tsx`
- Modify: `frontend/src/components/RecordFilters.test.tsx`
- Modify: `frontend/src/components/BusinessAnalysisCard.tsx`
- Modify: `frontend/src/components/BusinessAnalysisCard.test.tsx`

**Interfaces:**
- Produces: `NativeDateInput(props: NativeDateInputProps): JSX.Element`.
- Consumes: native input props except `type` and `className`; callers pass the existing `aria-label`, `value`, `min`, `max`, and `onChange`.
- Completes: all four business-record date input replacements.

- [ ] **Step 1: Write failing tests**

Add `NativeDateInput.test.tsx`:

```tsx
render(<NativeDateInput aria-label="开始日期" value="2026-07-01" max="2026-07-17" onChange={vi.fn()} />);
const input = screen.getByLabelText("开始日期");
expect(input).toHaveAttribute("type", "date");
expect(input).toHaveAttribute("max", "2026-07-17");
expect(input).toHaveClass("min-h-11", "pr-11");
```

Extend `RecordFilters.test.tsx` to assert both `开始日期` and `结束日期` contain `min-h-11` and `pr-11`. Extend the existing custom-range test in `BusinessAnalysisCard.test.tsx` to assert the same classes for `分析开始日期` and `分析结束日期` before changing their values.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
cd frontend
npm test -- NativeDateInput.test.tsx RecordFilters.test.tsx BusinessAnalysisCard.test.tsx
```

Expected: FAIL because `NativeDateInput` and the 44px sizing classes do not exist.

- [ ] **Step 3: Implement the shared component and replace all callers**

Create `NativeDateInput.tsx`:

```tsx
import type { InputHTMLAttributes } from "react";

type NativeDateInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "className" | "type">;

export function NativeDateInput(props: NativeDateInputProps) {
  return <input {...props} type="date" className="min-h-11 w-full rounded-md border border-input bg-background px-2 pr-11 text-base [color-scheme:light] [&::-webkit-calendar-picker-indicator]:h-11 [&::-webkit-calendar-picker-indicator]:w-11 [&::-webkit-calendar-picker-indicator]:cursor-pointer" />;
}
```

In `RecordFilters.tsx`, replace each native date input with `NativeDateInput`, passing its existing `aria-label`, `max`, `value`, and `onChange` unchanged. Keep the outer label grid.

In `BusinessAnalysisCard.tsx`, replace both custom-range inputs with `NativeDateInput`, retaining `max={custom.end || today}` for start and `min={custom.start}`/ `max={today}` for end. Change the custom-range labels to `grid gap-1 text-sm` so the enlarged fields wrap safely.

- [ ] **Step 4: Run focused tests and verify pass**

Run:

```powershell
cd frontend
npm test -- NativeDateInput.test.tsx RecordFilters.test.tsx BusinessAnalysisCard.test.tsx
```

Expected: PASS; existing custom-range query assertions still prove date values generate the same request.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/NativeDateInput.tsx frontend/src/components/NativeDateInput.test.tsx frontend/src/components/RecordFilters.tsx frontend/src/components/RecordFilters.test.tsx frontend/src/components/BusinessAnalysisCard.tsx frontend/src/components/BusinessAnalysisCard.test.tsx
git commit -m "feat: enlarge business record date inputs"
```

### Task 2: Allocate desktop chart space and compact the embedded trend

**Files:**
- Modify: `frontend/src/components/ChartPanel.tsx`
- Modify: `frontend/src/components/ChartPanel.test.tsx`
- Modify: `frontend/src/components/BusinessAnalysisCard.tsx`
- Modify: `frontend/src/components/BusinessAnalysisCard.test.tsx`
- Modify: `frontend/src/pages/BusinessRecordsPage.tsx`
- Modify: `frontend/src/pages/BusinessRecordsPage.test.tsx`

**Interfaces:**
- Produces: optional `heightClassName?: string` on `ChartPanelProps`; default remains `h-72 min-h-72`.
- Produces: desktop grid class `lg:grid-cols-[minmax(0,1fr)_minmax(30rem,32rem)]`.

- [ ] **Step 1: Write failing layout and chart-height tests**

In `ChartPanel.test.tsx`, render a populated line chart twice:

```tsx
const { rerender } = render(<ChartPanel title="趋势" kind="line" data={[{ label: "7月", revenue: 10 }]} xKey="label" valueKey="revenue" />);
expect(screen.getByTestId("chart-panel-plot")).toHaveClass("h-72", "min-h-72");
rerender(<ChartPanel title="趋势" kind="line" data={[{ label: "7月", revenue: 10 }]} xKey="label" valueKey="revenue" heightClassName="h-64 min-h-64" />);
expect(screen.getByTestId("chart-panel-plot")).toHaveClass("h-64", "min-h-64");
```

In `BusinessAnalysisCard.test.tsx`, after data loads, assert the embedded `营业额趋势` plot has `h-64` and `min-h-64`. In `BusinessRecordsPage.test.tsx`, assert the desktop content grid contains `lg:grid-cols-[minmax(0,1fr)_minmax(30rem,32rem)]` and retain the existing mobile-list assertion.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
cd frontend
npm test -- ChartPanel.test.tsx BusinessAnalysisCard.test.tsx BusinessRecordsPage.test.tsx
```

Expected: FAIL because the height override, plot test id, compact trend, and approved grid classes do not exist.

- [ ] **Step 3: Implement the optional height interface and layout**

In `ChartPanel.tsx`, add `heightClassName?: string` to props, default it to `"h-72 min-h-72"`, and use it only for populated charts:

```tsx
const plot = <div data-testid="chart-panel-plot" className={`${heightClassName} w-full`}><ResponsiveContainer width="100%" height="100%">{/* existing chart */}</ResponsiveContainer></div>;
```

Keep the no-data `h-64` state unchanged. In `BusinessAnalysisCard.tsx`, pass `heightClassName="h-64 min-h-64"` to its `营业额趋势` `ChartPanel`.

In `BusinessRecordsPage.tsx`, replace:

```tsx
lg:grid-cols-[minmax(0,1fr)_minmax(22rem,24rem)]
```

with:

```tsx
lg:grid-cols-[minmax(0,1fr)_minmax(30rem,32rem)]
```

Leave the sticky side panel and every `lg:hidden`/ `hidden lg:block` behavior unchanged.

- [ ] **Step 4: Run focused tests and verify pass**

Run:

```powershell
cd frontend
npm test -- ChartPanel.test.tsx BusinessAnalysisCard.test.tsx BusinessRecordsPage.test.tsx
```

Expected: PASS; revenue trends use 16rem, other charts retain 18rem, and mobile composition remains unchanged.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/ChartPanel.tsx frontend/src/components/ChartPanel.test.tsx frontend/src/components/BusinessAnalysisCard.tsx frontend/src/components/BusinessAnalysisCard.test.tsx frontend/src/pages/BusinessRecordsPage.tsx frontend/src/pages/BusinessRecordsPage.test.tsx
git commit -m "feat: widen business analysis trend layout"
```

### Task 3: Focused visual verification and PR gate

**Files:**
- No production files required unless Tasks 1–2 reveal a regression.

**Interfaces:**
- Consumes: completed Tasks 1–2 and the existing local authenticated frontend.
- Produces: evidence for desktop and mobile responsive acceptance criteria.

- [ ] **Step 1: Run the completed focused frontend test group**

```powershell
cd frontend
npm test -- NativeDateInput.test.tsx RecordFilters.test.tsx ChartPanel.test.tsx BusinessAnalysisCard.test.tsx BusinessRecordsPage.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Verify the local application at both breakpoints**

At desktop width (at least `1024px`), open `/database` with a selected store. Verify a visibly wider analysis side panel, a shorter revenue trend, and enlarged calendar trigger areas for both top filters and analysis custom dates.

At `390px` width, verify the page remains one column, all four date inputs are at least 44px high, and no horizontal page scrollbar appears while either custom range is visible.

- [ ] **Step 3: Run PR-quality frontend checks only when preparing the next PR update**

```powershell
cd frontend
npm test
npm run build
npm run test:e2e
```

Expected: all commands exit 0. If any check fails, invoke `superpowers:systematic-debugging` before code changes, then rerun the directly affected check.

- [ ] **Step 4: Commit only an intentional verification fix, if one is required**

If no code changed during visual verification, create no empty commit. If a targeted regression test or fix was required:

```powershell
git add <intentional-files-only>
git commit -m "fix: verify business analysis responsive layout"
```

