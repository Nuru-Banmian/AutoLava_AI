# 每日记账日历记录标记 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每日记账日期选择器为任意已浏览月份中的已保存记录显示蓝点，同时保持选择已有记录后的自动回填和局部修改。

**Architecture:** `LedgerDatePicker` 暴露当前日历浏览月份，`LedgerPage` 以门店和月份为查询键加载该月记录日期，并把日期集合传给既有 `MonthCalendar`。保存成功后通过现有按门店失效机制刷新月份查询；单日记录查询和 `LedgerForm` 的回填路径不变。

**Tech Stack:** React、TypeScript、TanStack Query、date-fns、Vitest、Testing Library、MSW。

## Global Constraints

- 仅真实保存的台账记录显示蓝点；空日期不显示标记。
- 月份请求失败或加载中时不推测记录日期，日期选择仍然可用。
- 已有记录的表单回填字段包括营业状态、收入项目或营业额、洗车数量、天气和活动。
- 不新增后端接口；复用 `GET /database/{storeId}/records` 的 `start`、`end`、`page` 和 `page_size` 参数。
- 保持仅可浏览至门店本地“今天”所在月份的现有规则。

---

### Task 1: 让日期选择器报告当前浏览月份

**Files:**
- Modify: `frontend/src/components/LedgerDatePicker.tsx`
- Test: `frontend/src/components/MonthCalendar.test.tsx`

**Interfaces:**
- Consumes: `LedgerDatePickerProps` 的现有 `value`、`today`、`recordedDates`、`onChange`。
- Produces: 可选回调 `onMonthChange(month: string): void`；当选择器打开且当前日历月份改变时调用，月份格式固定为 `YYYY-MM`。

- [ ] **Step 1: Write the failing test**

在 `LedgerDatePicker` 测试中传入 `onMonthChange`，打开选择器后断言回调接收初始月份；点击“上个月”后断言回调接收前一个月份。

```tsx
it("reports the visible calendar month while open", () => {
  const onMonthChange = vi.fn();
  render(<LedgerDatePicker value="2026-07-14" today="2026-07-15" recordedDates={new Set()} onChange={() => undefined} onMonthChange={onMonthChange} />);

  fireEvent.click(screen.getByRole("button", { name: "选择台账日期：2026年7月14日" }));
  expect(onMonthChange).toHaveBeenLastCalledWith("2026-07");
  fireEvent.click(screen.getByRole("button", { name: "上个月" }));
  expect(onMonthChange).toHaveBeenLastCalledWith("2026-06");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/components/MonthCalendar.test.tsx`

Expected: FAIL because `LedgerDatePickerProps` does not accept `onMonthChange`.

- [ ] **Step 3: Write minimal implementation**

Extend `LedgerDatePickerProps`, then notify only when the overlay is open so the page does not eagerly fetch every month from normal rerenders.

```tsx
export interface LedgerDatePickerProps {
  value: string;
  today: string;
  recordedDates: ReadonlySet<string>;
  onChange(date: string): void;
  onMonthChange?(month: string): void;
}

// Add this effect immediately after the existing effect that synchronizes `month` from `value`.
useEffect(() => {
  if (open) onMonthChange?.(month);
}, [month, onMonthChange, open]);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- src/components/MonthCalendar.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- frontend/src/components/LedgerDatePicker.tsx frontend/src/components/MonthCalendar.test.tsx
git commit -m "feat: report visible ledger calendar month"
```

### Task 2: 加载并展示指定月份的记录日期

**Files:**
- Modify: `frontend/src/lib/user-api.ts`
- Modify: `frontend/src/pages/LedgerPage.tsx`
- Test: `frontend/src/pages/LedgerPage.test.tsx`

**Interfaces:**
- Consumes: `onMonthChange(month)`，`DatabaseResponse.items`，现有 `api<DatabaseResponse>`。
- Produces: `ledgerMonthKey(storeId: number, month: string)`，以及传给 `LedgerDatePicker` 的 `recordedDates: ReadonlySet<string>`。

- [ ] **Step 1: Write the failing test**

添加页面测试：打开日期选择器，切到 2026 年 6 月；MSW 对 `GET /api/database/1/records` 返回 6 月 4 日记录；断言请求范围为 2026-06-01 至 2026-06-30，且日历按钮具有“已有记录”无障碍名称。

```tsx
it("marks records from the visible historical month", async () => {
  renderLedger([
    http.get("/api/database/1/records", ({ request }) => {
      const url = new URL(request.url);
      if (url.searchParams.get("start") === "2026-06-01") {
        return HttpResponse.json({ items: [{ ...recordSnapshot("10.00"), date: "2026-06-04" }], categories: [], sum_daily_revenue: "10.00", total: 1, page: 1, page_size: 200 });
      }
      return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 });
    }),
  ]);

  fireEvent.click(await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" }));
  fireEvent.click(screen.getByRole("button", { name: "上个月" }));
  expect(await screen.findByRole("button", { name: "2026年6月4日，已有记录" })).toBeEnabled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/pages/LedgerPage.test.tsx`

Expected: FAIL because changing the visible month does not trigger a month-scoped query and the record is not marked.

- [ ] **Step 3: Write minimal implementation**

Define a stable month key and use `startOfMonth`/`endOfMonth` to request up to 200 records for the visible month. Keep the current selected record included until the month response arrives so a selected existing date remains correctly labelled.

```ts
export const ledgerMonthKey = (storeId: number, month: string) => ["ledgerMonth", storeId, month] as const;
```

```tsx
const [visibleMonth, setVisibleMonth] = useState(date.slice(0, 7));
const monthDates = useQuery({
  queryKey: selected ? ledgerMonthKey(selected.id, visibleMonth) : ["ledger", "month", "none"],
  enabled: Boolean(selected && visibleMonth),
  queryFn: () => {
    const first = parseISO(`${visibleMonth}-01`);
    const start = format(startOfMonth(first), "yyyy-MM-dd");
    const end = format(endOfMonth(first), "yyyy-MM-dd");
    return api<DatabaseResponse>(`/database/${selected!.id}/records?start=${start}&end=${end}&page=1&page_size=200`);
  },
});
const recordedDates = useMemo(() => new Set([...(monthDates.data?.items.map((item) => item.date) ?? []), ...(record.data ? [record.data.date] : [])]), [monthDates.data, record.data]);
```

Pass `onMonthChange={setVisibleMonth}` to `LedgerDatePicker`; remove the former `recent`-derived dates from this set while leaving the recent-list query untouched.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- src/pages/LedgerPage.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- frontend/src/lib/user-api.ts frontend/src/pages/LedgerPage.tsx frontend/src/pages/LedgerPage.test.tsx
git commit -m "feat: mark recorded dates across ledger calendar months"
```

### Task 3: 验证保存刷新和已有记录自动回填

**Files:**
- Modify: `frontend/src/pages/LedgerPage.test.tsx`
- Modify: `frontend/src/pages/LedgerPage.tsx`（仅当测试证明现有失效范围未覆盖 `ledgerMonthKey` 时）

**Interfaces:**
- Consumes: `invalidateUserData(client, storeId)` 的门店作用域失效逻辑，以及现有 `LedgerForm` 的 `record` 属性。
- Produces: 保存后刷新当月蓝点；选择已有记录后保持已保存字段为表单初始值。

- [ ] **Step 1: Write the failing test**

添加测试：月份查询第一次返回空集合，保存 7 月 15 日记录后第二次返回该日期；重新打开日历并断言该日期标为“已有记录”。同时在已有记录测试中断言收入、天气、洗车数量和活动的输入值来自记录快照。

```tsx
expect(screen.getByLabelText("现金")).toHaveValue("12.30");
fireEvent.click(screen.getByRole("button", { name: "天气" }));
expect(screen.getByLabelText("天气")).toHaveValue("晴");
fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
expect(screen.getByLabelText("洗车数量")).toHaveValue(3);
expect(screen.getByLabelText("活动")).toHaveValue("促销");
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/pages/LedgerPage.test.tsx`

Expected: FAIL because the new `ledgerMonthKey` is not yet included in the existing `invalidateUserData` predicate.

- [ ] **Step 3: Write minimal implementation**

If required, extend the existing predicate to invalidate all ledger query families for the selected store; no new mutation flow is needed.

```ts
if (queryKey[0] === "ledger" || queryKey[0] === "database" || queryKey[0] === "ledgerMonth") {
  const storeKeyIndex = queryKey[0] === "ledgerMonth" ? 1 : 2;
  return queryKey[storeKeyIndex] === storeId;
}
```

Keep `LedgerPage` passing the selected date’s `RecordSnapshot` to `LedgerForm`; do not overwrite form state from month-marker data.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- src/pages/LedgerPage.test.tsx`

Expected: PASS.

- [ ] **Step 5: Run focused frontend verification**

Run: `npm test -- src/components/MonthCalendar.test.tsx src/pages/LedgerPage.test.tsx; npm run build`

Expected: both test files pass and TypeScript/Vite production build exits with code 0.

- [ ] **Step 6: Commit**

```powershell
git add -- frontend/src/lib/user-api.ts frontend/src/pages/LedgerPage.tsx frontend/src/pages/LedgerPage.test.tsx
git commit -m "test: cover ledger calendar marker refresh and autofill"
```
