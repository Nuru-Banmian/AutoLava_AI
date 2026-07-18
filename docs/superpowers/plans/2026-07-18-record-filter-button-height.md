# 营业记录筛选按钮高度统一 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the four record-filter action buttons match the 44px date-input height.

**Architecture:** Change only local Tailwind classes in `RecordFilters`. Extend the existing component test to lock the visual height contract while retaining current preset, export, disabled, and responsive behavior.

**Tech Stack:** React, TypeScript, Tailwind CSS, Vitest, React Testing Library.

## Global Constraints

- Change only the 本月、上月、自定义、导出当前范围 buttons in `RecordFilters`.
- Every target button must include `min-h-11` (44px).
- Preserve current horizontal padding, text size, selected state, disabled state, export logic, labels, and wrap behavior.
- Do not modify `NativeDateInput`, date-range logic, APIs, export requests, other pages, or shared button components.
- Run only focused frontend tests for this low-risk local style change.

---

## File Structure

- Modify: `frontend/src/components/RecordFilters.tsx` — add the local height class to the four target buttons.
- Modify: `frontend/src/components/RecordFilters.test.tsx` — assert the four rendered buttons retain the 44px class and existing behavior.

### Task 1: Unify record-filter action heights

**Files:**
- Modify: `frontend/src/components/RecordFilters.tsx`
- Modify: `frontend/src/components/RecordFilters.test.tsx`

**Interfaces:**
- Consumes: existing `RecordFiltersProps` and button behavior.
- Produces: the unchanged `RecordFilters` API with a 44px local action-button visual contract.

- [ ] **Step 1: Write the failing height-contract test**

In `RecordFilters.test.tsx`, render the existing current-month fixture and assert every target button has `min-h-11`:

```tsx
for (const name of ["本月", "上月", "自定义", "导出当前范围"]) {
  expect(screen.getByRole("button", { name })).toHaveClass("min-h-11");
}
```

Keep the existing assertions for selected preset, preset range emission, export callback, disabled export state, and error message.

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```powershell
cd frontend
npm test -- RecordFilters.test.tsx
```

Expected: FAIL because the four buttons currently lack `min-h-11`.

- [ ] **Step 3: Apply the minimal local class change**

In `RecordFilters.tsx`, append `min-h-11` to the three preset button class strings and to the export button class string. Do not alter any other class, property, callback, or label.

The resulting preset button class must include:

```tsx
"min-h-11 rounded-md border border-border px-3 py-2 text-sm aria-pressed:bg-primary aria-pressed:text-primary-foreground"
```

The resulting export button class must include:

```tsx
"min-h-11 rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60"
```

- [ ] **Step 4: Run the focused test and verify pass**

Run:

```powershell
cd frontend
npm test -- RecordFilters.test.tsx
```

Expected: PASS, preserving all existing test cases.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/RecordFilters.tsx frontend/src/components/RecordFilters.test.tsx
git commit -m "style: align record filter button heights"
```

