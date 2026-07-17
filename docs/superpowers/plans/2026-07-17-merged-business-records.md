# Merged Business Records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `/database` 改造成统一的“营业记录”页面：左侧是可筛选、分页的 Excel 式日记录表，右侧是选中记录详情和统一的经营分析卡片；移动端使用紧凑列表与底部详情抽屉，并删除旧 `/charts` 前端链路。

**Architecture:** 保留现有 `/api/database/{resource}` 与 `/api/charts/{store_id}` 路径和 React Query key 语义。后端仅对 charts 响应做向后兼容的加法扩展，提供比较区间、曲线粒度元数据和“计入/不计入总营业额”两组构成。前端用一个页面容器管理彼此独立的记录范围与分析范围；展示组件保持无请求、可独立测试，所有金额继续以字符串/整数分为边界，避免浮点误差。

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async, pytest; React 19, TypeScript, TanStack Query, date-fns, Recharts, Radix UI, Tailwind CSS, Vitest/Testing Library, Playwright.

## Global Constraints

- 实施前先将 `codex/management-center-optimization` 合入或同步到本分支，再解决文件级冲突；不得反向覆盖该分支已经确定的收入分类和 query-key 行为。
- 本分支不得重命名任何后端 API 路径，也不得更改 `chartsKey`、`databaseKey` 和 `invalidateUserData` 的根 key 语义。
- `/database` 是唯一页面地址；删除 `/charts` 路由和入口，不增加重定向。
- 记录查询固定 `page_size=15`，日期降序由后端现有查询保证；不得在前端对单页数据重新假装成全量排序或汇总。
- 记录范围与分析范围彼此独立；切换门店时二者都重置为当前月，页码重置为 1，并自动选择当前页第一条记录。
- legacy total-only 记录参与 KPI 与曲线，不出现在收入构成中。
- 未传 `category_id` 时 `categories` 只返回计入分类；显式 `category_id` 保留旧筛选覆盖语义，统一页面不发送它。
- 计入总营业额分类显示金额与其在“已分类计入金额”中的占比；不计入分类只显示金额。两组默认各显示配置顺序前 5 项，可独立展开/收起，不虚构“其他”。
- 桌面右栏 sticky 且自身可滚动；移动端记录列表固定日期/状态/营业额三列，点击后从底部打开详情，不允许横向滚动。
- 每个任务严格执行红—绿—重构；测试失败必须是预期失败，不得跳过失败步骤直接写实现。

## File Responsibility Map

| File | Responsibility |
|---|---|
| `backend/app/schemas/charts.py` | charts 加法响应契约：范围、比较 KPI、两组收入构成 |
| `backend/app/api/routes/charts.py` | 验证比较参数并收集当前门店分类 ID；保持旧参数兼容 |
| `backend/app/services/analytics.py` | 当前区间/比较区间聚合，分类分组和已分类计入金额 |
| `backend/tests/api/test_charts.py` | HTTP 参数校验、默认兼容和稳定 JSON 契约 |
| `backend/tests/services/test_analytics.py` | legacy、分组、排序、比较区间的业务规则 |
| `frontend/src/lib/analysis-range.ts` | 本月、上月、近 6 月、自定义范围及粒度的纯函数 |
| `frontend/src/lib/analysis-range.test.ts` | 月末、跨年、短月、自定义阈值测试 |
| `frontend/src/api/types.ts` | charts 新增字段的 TypeScript 镜像类型 |
| `frontend/src/components/ChartPanel.tsx` | 可嵌入经营分析卡片的曲线内容，不强制嵌套 Card |
| `frontend/src/components/IncomeComposition.tsx` | 两组构成、分隔线、占比和独立展开状态 |
| `frontend/src/components/BusinessAnalysisCard.tsx` | 分析范围控件、请求、KPI、曲线和收入构成的单卡片 |
| `frontend/src/components/RecordFilters.tsx` | 本月/上月/自定义记录范围和导出操作状态 |
| `frontend/src/components/RecordTable.tsx` | 桌面表格、选中态、错误/空态与分页控件 |
| `frontend/src/components/MobileRecordList.tsx` | 移动端固定三列列表与选中事件 |
| `frontend/src/components/MobileRecordSheet.tsx` | 移动端底部详情抽屉，复用 `RecordDetailPanel` 并恢复触发行焦点 |
| `frontend/src/components/RecordDetailPanel.tsx` | 选中日详情，正确反映非营业状态、洗车数和活动摘要 |
| `frontend/src/components/RecordDetailPanel.test.tsx` | 非营业状态和详情摘要回归测试 |
| `frontend/src/pages/BusinessRecordsPage.tsx` | 页面编排、记录查询/选择、管理操作和响应式布局 |
| `frontend/src/pages/BusinessRecordsPage.test.tsx` | 页面级请求、自动选择、独立状态、管理权限和错误隔离 |
| `frontend/src/router.tsx` | `/database` 指向新页并删除 `/charts` |
| `frontend/src/navigation/modules.ts` | 桌面导航只保留“营业记录” |
| `frontend/src/pages/MorePage.tsx` | 删除旧经营分析入口 |
| `frontend/src/layouts/AppShell.tsx` | 删除 `/charts` 专用图标映射 |
| `frontend/src/App.test.tsx` | 新导航与旧链接消失的回归测试 |
| `frontend/tests/daily-flow.spec.ts` | 合并后的核心用户流程 |
| `frontend/tests/responsive.spec.ts` | 桌面双栏/sticky 与 320px 移动端列表/抽屉 |

---

### Task 1: Extend analytics without breaking existing callers

**Files:**
- Modify: `backend/tests/services/test_analytics.py`
- Modify: `backend/tests/api/test_charts.py`
- Modify: `backend/app/schemas/charts.py`
- Modify: `backend/app/api/routes/charts.py`
- Modify: `backend/app/services/analytics.py`

**Interfaces introduced:**

```python
class ChartRange(BaseModel):
    start: str
    end: str
    bucket: Literal["day", "month"]


class ComparisonKpis(BaseModel):
    start: str
    end: str
    total_revenue: str
    open_days: int
    average_revenue: str


class ChartsResponse(BaseModel):
    kpis: ChartKpis
    range: ChartRange
    comparison_kpis: ComparisonKpis | None
    classified_included_total: str
    daily: list[DailyRevenue]
    categories: list[CategoryComposition]
    excluded_categories: list[CategoryComposition]
    monthly: list[MonthlyRevenue]
    weather: list[WeatherRevenue]
    weekday: list[WeekdayRevenue]
```

The route keeps `category_id` behavior intact and adds:

```python
compare_start: date | None = None
compare_end: date | None = None
bucket: Literal["day", "month"] = "day"
```

- [ ] **Step 1: Add failing service tests for grouped composition and comparison**

Keep `_seed_records` backward compatible. In the new test, destructure its two existing IDs, add one excluded category, attach `7.00` to the first July record, and request a June comparison:

```python
store, category_ids = await _seed_records(db_session, suffix="-groups")
cash_id, card_id = category_ids
coupon = IncomeCategory(
    store_id=store.id,
    name="优惠券",
    include_in_total=False,
    sort_order=3,
)
db_session.add(coupon)
await db_session.flush()
first_record = await db_session.scalar(
    select(StoreDailyRecord)
    .where(StoreDailyRecord.store_id == store.id)
    .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
)
assert first_record is not None
db_session.add(
    DailyIncomeItem(record_id=first_record.id, category_id=coupon.id, amount=Decimal("7.00"))
)
await db_session.flush()

result = await AnalyticsService(db_session).calculate(
    store_id=store.id,
    start=date(2026, 7, 1),
    end=date(2026, 7, 31),
    category_ids=[cash_id, card_id],
    included_category_ids=[cash_id, card_id],
    excluded_category_ids=[coupon.id],
    compare_start=date(2026, 6, 1),
    compare_end=date(2026, 6, 30),
    bucket="day",
)

assert result["range"] == {"start": "2026-07-01", "end": "2026-07-31", "bucket": "day"}
assert result["classified_included_total"] == "350.00"
assert result["excluded_categories"] == [
    {"category_id": coupon.id, "category_name": "优惠券", "amount": "7.00"}
]
assert result["comparison_kpis"] == {
    "start": "2026-06-01",
    "end": "2026-06-30",
    "total_revenue": "0.00",
    "open_days": 0,
    "average_revenue": "0.00",
}
```

Also extend `test_total_only_records_affect_trend_not_composition`:

```python
assert result["classified_included_total"] == "0.00"
assert result["excluded_categories"] == []
```

Add a regression in which an `IncomeCategory(is_active=False)` is still referenced by a July item; assert it remains in the appropriate composition group and retains its historical name/order.

- [ ] **Step 2: Run the service tests and confirm the expected signature/field failure**

Run from `backend`:

```sh
pytest tests/services/test_analytics.py -q
```

Expected: FAIL because `AnalyticsService.calculate` does not accept the new arguments and does not return the new fields.

- [ ] **Step 3: Add failing API contract and validation tests**

Add tests for the default bucket, explicit month bucket, pair validation, reversed comparison, and grouped response. The key compatibility assertion is that an old request without new query parameters still succeeds:

```python
response = await auth_client.get(
    f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31"
)
payload = response.json()
assert response.status_code == 200
assert payload["range"]["bucket"] == "day"
assert payload["comparison_kpis"] is None
```

Pair validation must cover both missing sides:

```python
for suffix in ("&compare_start=2026-06-01", "&compare_end=2026-06-30"):
    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31{suffix}"
    )
    assert response.status_code == 422
```

Update the exact empty response assertion to include:

```python
"range": {"start": "2026-07-01", "end": "2026-07-31", "bucket": "day"},
"comparison_kpis": None,
"classified_included_total": "0.00",
"excluded_categories": [],
```

- [ ] **Step 4: Run API tests and confirm the new contract fails**

```sh
pytest tests/api/test_charts.py -q
```

Expected: FAIL on absent fields and absent parameter validation.

- [ ] **Step 5: Implement the schema, route validation, and one-pass category grouping**

In `charts.py`, import `Literal`, add the schemas above, and add the fields to `ChartsResponse` in the stated order.

In the route, validate the optional comparison pair before querying:

```python
if (compare_start is None) != (compare_end is None):
    raise HTTPException(422, "compare_start and compare_end must be provided together")
if compare_start is not None and compare_end is not None and compare_start > compare_end:
    raise HTTPException(422, "compare_start must be on or before compare_end")
```

Fetch all current-store categories once in configuration order, derive `included_ids` and `excluded_ids`, and preserve legacy selection:

```python
all_categories = list(
    await session.scalars(
        select(IncomeCategory)
        .where(IncomeCategory.store_id == access.store.id)
        .order_by(IncomeCategory.sort_order, IncomeCategory.id)
    )
)
owned_ids = {category.id for category in all_categories}
included_ids = [category.id for category in all_categories if category.include_in_total]
excluded_ids = [category.id for category in all_categories if not category.include_in_total]
selected_ids = included_ids if category_id is None else list(dict.fromkeys(category_id))
if not set(selected_ids).issubset(owned_ids):
    raise HTTPException(422, "All categories must belong to the requested store")
```

Refactor `AnalyticsService` into private `_load_records`, `_kpis`, and `_composition` helpers. The public call must accept defaults so direct existing service callers remain valid:

```python
async def calculate(
    self,
    *,
    store_id: int,
    start: date,
    end: date,
    category_ids: list[int],
    included_category_ids: list[int] | None = None,
    excluded_category_ids: list[int] | None = None,
    compare_start: date | None = None,
    compare_end: date | None = None,
    bucket: Literal["day", "month"] = "day",
) -> dict:
```

Use the ordered union of the three ID lists to load names once. Sum item amounts only for known IDs. Compute `classified_included_total` from all `included_category_ids`, not only `category_ids`; this preserves explicit legacy category filtering without corrupting the new denominator. Build comparison KPI from comparison records only and do not compute comparison composition.

When `included_category_ids` is `None`, treat `category_ids` as the included IDs; when `excluded_category_ids` is `None`, treat it as an empty list. These defaults are required for the unchanged direct service tests.

- [ ] **Step 6: Run focused and full backend checks**

```sh
pytest tests/services/test_analytics.py tests/api/test_charts.py -q
ruff check app tests
pytest -q
```

Expected: all PASS. Confirm the unchanged explicit excluded `category_id` test still passes.

- [ ] **Step 7: Commit the backend contract**

```sh
git add backend/app/schemas/charts.py backend/app/api/routes/charts.py backend/app/services/analytics.py backend/tests/api/test_charts.py backend/tests/services/test_analytics.py
git commit -m "feat: extend business analytics contract"
```

---

### Task 2: Make date-range behavior a tested pure function

**Files:**
- Create: `frontend/src/lib/analysis-range.ts`
- Create: `frontend/src/lib/analysis-range.test.ts`
- Modify: `frontend/src/api/types.ts`

**Interfaces introduced:**

```ts
import type { ChartBucket } from "@/api/types";

export type AnalysisPreset = "current-month" | "previous-month" | "six-months" | "custom";

export interface ResolvedAnalysisRange {
  start: string;
  end: string;
  bucket: ChartBucket;
  compareStart: string | null;
  compareEnd: string | null;
}

export function resolveAnalysisRange(
  preset: AnalysisPreset,
  today: string,
  custom?: { start: string; end: string },
): ResolvedAnalysisRange;
```

- [ ] **Step 1: Write failing range tests**

Use fixed local dates and exact assertions:

```ts
expect(resolveAnalysisRange("current-month", "2026-07-17")).toEqual({
  start: "2026-07-01",
  end: "2026-07-17",
  bucket: "day",
  compareStart: "2026-06-01",
  compareEnd: "2026-06-17",
});

expect(resolveAnalysisRange("previous-month", "2026-03-31")).toEqual({
  start: "2026-02-01",
  end: "2026-02-28",
  bucket: "day",
  compareStart: "2026-01-01",
  compareEnd: "2026-01-31",
});

expect(resolveAnalysisRange("six-months", "2026-02-10")).toEqual({
  start: "2025-09-01",
  end: "2026-02-10",
  bucket: "month",
  compareStart: "2025-03-01",
  compareEnd: "2025-08-10",
});

expect(resolveAnalysisRange("custom", "2026-07-17", {
  start: "2026-01-01",
  end: "2026-03-04",
})).toMatchObject({ bucket: "month", compareStart: null, compareEnd: null });
```

Add boundary cases for a 62-day custom range (`day`), a 63-day custom range (`month`), and reversed custom dates throwing `RangeError`.

Also assert `resolveAnalysisRange("six-months", "2026-08-31")` clamps the shifted comparison end to `2026-02-28`, proving the “same day number, otherwise month end” rule.

- [ ] **Step 2: Run the new test and confirm the missing-module failure**

```sh
npm test -- src/lib/analysis-range.test.ts
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the pure function with date-fns**

Use `parseISO`, `startOfMonth`, `endOfMonth`, `subMonths`, `differenceInCalendarDays`, and `format`. For current-month comparison, clamp the previous-month day to its real month end:

```ts
const previousMonthStart = startOfMonth(subMonths(now, 1));
const previousMonthEnd = endOfMonth(previousMonthStart);
const samePeriodEnd = new Date(
  previousMonthStart.getFullYear(),
  previousMonthStart.getMonth(),
  Math.min(now.getDate(), previousMonthEnd.getDate()),
);
```

For custom ranges, calculate inclusive length as `differenceInCalendarDays(end, start) + 1`.

- [ ] **Step 4: Extend `ChartsResponse` types exactly**

```ts
export type ChartBucket = "day" | "month";
export interface ComparisonKpis {
  start: string;
  end: string;
  total_revenue: string;
  open_days: number;
  average_revenue: string;
}
export interface CategoryComposition {
  category_id: number;
  category_name: string;
  amount: string;
}
```

Add `range`, `comparison_kpis`, `classified_included_total`, and `excluded_categories` to the existing response; do not remove weather, weekday, daily, monthly, or existing KPI fields.

- [ ] **Step 5: Run tests/build and commit**

```sh
npm test -- src/lib/analysis-range.test.ts
npm run build
git add frontend/src/lib/analysis-range.ts frontend/src/lib/analysis-range.test.ts frontend/src/api/types.ts
git commit -m "feat: define analysis date ranges"
```

Expected: PASS.

---

### Task 3: Build the unified analysis card

**Files:**
- Modify: `frontend/src/components/ChartPanel.tsx`
- Modify: `frontend/src/components/ChartPanel.test.tsx`
- Create: `frontend/src/components/IncomeComposition.tsx`
- Create: `frontend/src/components/IncomeComposition.test.tsx`
- Create: `frontend/src/components/BusinessAnalysisCard.tsx`
- Create: `frontend/src/components/BusinessAnalysisCard.test.tsx`

**Interfaces introduced:**

```ts
interface IncomeCompositionProps {
  included: CategoryComposition[];
  excluded: CategoryComposition[];
  includedTotal: string;
}

interface BusinessAnalysisCardProps {
  storeId: number;
  today: string;
}
```

- [ ] **Step 1: Add failing `ChartPanel` embedded-mode test**

Render the following and assert the title and chart exist but no outer element carries the card class. Keep the existing tooltip money-format test.

```tsx
<ChartPanel
  embedded
  title="营业额变化"
  data={[{ label: "7月1日", revenue: 100, revenue_raw: "100.00" }]}
  kind="line"
  xKey="label"
  valueKey="revenue"
/>
```

- [ ] **Step 2: Add failing income composition tests**

Cover all product rules in one fixture:

```ts
const included = Array.from({ length: 6 }, (_, index) => ({
  category_id: index + 1,
  category_name: `计入-${index + 1}`,
  amount: index === 0 ? "50.00" : "10.00",
}));
const excluded = Array.from({ length: 6 }, (_, index) => ({
  category_id: index + 11,
  category_name: `不计入-${index + 1}`,
  amount: "2.00",
}));
```

Assert initial visibility stops at item 5 in each group, `计入-1` shows `50.0%`, excluded rows contain no `%`, the divider label is visible, and expanding the included group does not expand the excluded group. Add single-category and empty tests: one included category keeps its amount/share text but renders no proportion bar; no classified included amount explains that legacy totals were not guessed into categories. Assert the excluded-group note says those amounts do not enter total revenue or daily average.

- [ ] **Step 3: Add failing analysis-card request and rendering tests**

With MSW, assert the initial request contains:

```text
start=2026-07-01
end=2026-07-17
compare_start=2026-06-01
compare_end=2026-06-17
bucket=day
```

Then assert:

- KPI shows current total and comparison change.
- Selecting `近 6 月` sends `bucket=month` and the chart uses monthly rows.
- Selecting `自定义` reveals two labeled date inputs and omits comparison parameters.
- Analysis request failure renders only an alert inside the card with a retry button.
- A failed background refresh keeps the cached card values visible and adds an accessible “刷新失败” warning.
- Empty data renders zero KPIs and “暂无数据”, not a page-level failure.
- The card exposes current/comparison dates, bucket and key values as visible or screen-reader text so the chart has a textual equivalent.

- [ ] **Step 4: Run component tests and confirm failure**

```sh
npm test -- src/components/ChartPanel.test.tsx src/components/IncomeComposition.test.tsx src/components/BusinessAnalysisCard.test.tsx
```

Expected: FAIL for missing components and embedded prop.

- [ ] **Step 5: Implement embedded chart content**

Add `embedded?: boolean` to `ChartPanel`. Build the same header/content once and return it in a fragment when embedded; otherwise wrap it in `Card`. Preserve the fixed chart height and tooltip formatting.

- [ ] **Step 6: Implement exact-cent composition percentages**

Reuse `amountToCents`. Derive tenths of a percent without floating-point money arithmetic:

```ts
function percentageLabel(amount: string, total: string) {
  const amountCents = amountToCents(amount) ?? 0n;
  const totalCents = amountToCents(total) ?? 0n;
  if (totalCents <= 0n) return "0.0%";
  const tenths = (amountCents * 1000n + totalCents / 2n) / totalCents;
  return `${Number(tenths) / 10}%`;
}
```

Use the numeric percentage only as a CSS width capped at 100; keep the string amount as the source of truth. Only render proportion bars when at least two included categories have data. Render a semantic heading for each group, a horizontal separator between them, and the explanatory text required by the tests.

- [ ] **Step 7: Implement the single analysis card**

The component owns `preset` and custom inputs. Resolve the range with Task 2, build `URLSearchParams`, and query with the unchanged root key:

```ts
const params = new URLSearchParams({
  start: range.start,
  end: range.end,
  bucket: range.bucket,
});
if (range.compareStart && range.compareEnd) {
  params.set("compare_start", range.compareStart);
  params.set("compare_end", range.compareEnd);
}
const query = useQuery({
  queryKey: chartsKey(storeId, params.toString()),
  queryFn: () => api<ChartsResponse>(`/charts/${storeId}?${params}`),
});
```

Select `daily` or `monthly` from `range.bucket`, map money strings to `revenue_raw` for chart tooltips, and place `IncomeComposition` below the curve inside the same `CardContent`. Calculate comparison amount/percentage from `amountToCents` values. Show comparison delta only when `comparison_kpis` is present; if the comparison total is zero, show a neutral “上期为 0，暂无可比增幅” message rather than infinity. Use “该范围暂无经营数据” for an empty series.

- [ ] **Step 8: Run tests/build and commit**

```sh
npm test -- src/components/ChartPanel.test.tsx src/components/IncomeComposition.test.tsx src/components/BusinessAnalysisCard.test.tsx
npm run build
git add frontend/src/components/ChartPanel.tsx frontend/src/components/ChartPanel.test.tsx frontend/src/components/IncomeComposition.tsx frontend/src/components/IncomeComposition.test.tsx frontend/src/components/BusinessAnalysisCard.tsx frontend/src/components/BusinessAnalysisCard.test.tsx
git commit -m "feat: add unified business analysis card"
```

Expected: PASS.

---

### Task 4: Build record discovery components

**Files:**
- Create: `frontend/src/components/RecordFilters.tsx`
- Create: `frontend/src/components/RecordFilters.test.tsx`
- Create: `frontend/src/components/RecordTable.tsx`
- Create: `frontend/src/components/RecordTable.test.tsx`
- Create: `frontend/src/components/MobileRecordList.tsx`
- Create: `frontend/src/components/MobileRecordList.test.tsx`
- Create: `frontend/src/components/MobileRecordSheet.tsx`
- Create: `frontend/src/components/MobileRecordSheet.test.tsx`
- Create: `frontend/src/components/RecordDetailPanel.tsx`
- Create: `frontend/src/components/RecordDetailPanel.test.tsx`
- Delete: `frontend/src/components/RecordDetail.tsx`

**Interfaces introduced:**

```ts
export interface RecordRange {
  mode: "current-month" | "previous-month" | "custom";
  start: string;
  end: string;
}

interface RecordTableProps {
  records: RecordSnapshot[];
  selectedId: number | null;
  page: number;
  total: number;
  pageSize: 15;
  loading: boolean;
  error: Error | null;
  onSelect: (record: RecordSnapshot) => void;
  onPageChange: (page: number) => void;
  onRetry: () => void;
}

export function currentMonthRecordRange(today: string): RecordRange;
export function previousMonthRecordRange(today: string): RecordRange;

interface RecordFiltersProps {
  value: RecordRange;
  today: string;
  exporting: boolean;
  exportError: string;
  onChange: (range: RecordRange) => void;
  onExport: () => void;
}
```

- [ ] **Step 1: Write failing filter tests**

Assert the three modes exist, current month is initially pressed, custom mode reveals labeled start/end inputs, invalid/reversed custom input disables applying, export calls `onExport` without changing the active range, and export loading/error text is announced in Chinese.

- [ ] **Step 2: Write failing desktop table tests**

Assert headers are exactly `日期 / 状态 / 总营业额 / 天气`, row activation calls `onSelect`, selected row exposes `aria-selected="true"`, loading/error/empty states occupy the table region, retry calls `onRetry`, and page buttons obey `Math.ceil(total / 15)`. Loading must render skeleton rows rather than previous-store cell values.

- [ ] **Step 3: Write failing mobile list/sheet tests**

Assert only the three fixed fields appear in `MobileRecordList`, long values do not introduce extra columns, and clicking a row opens a `MobileRecordSheet` containing `RecordDetailPanel`. The sheet must have an accessible title containing the date. After closing, assert focus returns to the exact row button that opened it.

- [ ] **Step 4: Add the non-business status regression test**

Render `RecordDetailPanel` with `is_open: "休息"`, `wash_count: 0`, and an activity. Assert it shows `休息`, not `营业`, and includes both wash count and activity summary. Repeat status assertion for `天气停业`.

- [ ] **Step 5: Run the focused tests and confirm expected failures**

```sh
npm test -- src/components/RecordFilters.test.tsx src/components/RecordTable.test.tsx src/components/MobileRecordList.test.tsx src/components/MobileRecordSheet.test.tsx src/components/RecordDetailPanel.test.tsx
```

Expected: FAIL because the new components do not exist and the detail regression is not yet encoded.

- [ ] **Step 6: Implement filters and table semantics**

Use real `<table>`, `<thead>`, `<tbody>`, and `<button>` controls inside cells. Do not attach click handlers only to `<tr>`. Calculate total pages from server `total`; disable previous on page 1 and next on the last page. Keep the selected row visible by style only—do not reorder records.

- [ ] **Step 7: Implement mobile list and bottom sheet**

Use a CSS grid `grid-cols-[minmax(0,1fr)_auto_auto]` and `overflow-x-hidden`. Compose the existing Radix `Sheet` primitives with `side="bottom"`; render `RecordDetailPanel` inside, not a second copy of field formatting. Give the content `pb-[calc(1rem+env(safe-area-inset-bottom))]`. Pass the triggering row button ref to the sheet and restore it from `onCloseAutoFocus` after preventing the default focus target.

- [ ] **Step 8: Update detail status and summary fields**

Move the existing component to `RecordDetailPanel.tsx` and rename its export. Display `record.is_open` directly with a status-specific badge variant/class. Preserve edit/manage actions. Place wash count and activity near the top summary so they appear in both desktop right detail and mobile sheet.

- [ ] **Step 9: Run tests/build and commit**

```sh
npm test -- src/components/RecordFilters.test.tsx src/components/RecordTable.test.tsx src/components/MobileRecordList.test.tsx src/components/MobileRecordSheet.test.tsx src/components/RecordDetailPanel.test.tsx
npm run build
git add frontend/src/components/RecordFilters.tsx frontend/src/components/RecordFilters.test.tsx frontend/src/components/RecordTable.tsx frontend/src/components/RecordTable.test.tsx frontend/src/components/MobileRecordList.tsx frontend/src/components/MobileRecordList.test.tsx frontend/src/components/MobileRecordSheet.tsx frontend/src/components/MobileRecordSheet.test.tsx frontend/src/components/RecordDetail.tsx frontend/src/components/RecordDetailPanel.tsx frontend/src/components/RecordDetailPanel.test.tsx
git commit -m "feat: add paginated record browsing components"
```

Expected: PASS.

---

### Task 5: Assemble the unified Business Records page

**Files:**
- Create: `frontend/src/pages/BusinessRecordsPage.tsx`
- Create: `frontend/src/pages/BusinessRecordsPage.test.tsx`
- Modify: `frontend/src/router.tsx`
- Delete: `frontend/src/pages/DatabasePage.tsx`
- Delete: `frontend/src/pages/DatabasePage.test.tsx`

- [ ] **Step 1: Port existing management tests before deleting the old page**

Copy the admin/user/delete-conflict/rollback cases from `DatabasePage.test.tsx` to `BusinessRecordsPage.test.tsx`, changing only visible page labels and interactions needed by the new table. Keep assertions proving:

- users can edit but cannot manage;
- admins can open audit history, delete with expected version, reload on 409, and rollback;
- stale mutations from a previously selected store do not display success in the new store.

- [ ] **Step 2: Add failing orchestration tests**

Add MSW request capture and assert the initial database call is:

```text
/database/{storeId}/records?start=2026-07-01&end=2026-07-31&page=1&page_size=15
```

Cover these behaviors:

1. Initial success auto-selects the first returned item.
2. Changing record range resets page to 1 and selects the new first item.
3. Changing page selects that page's first item.
4. Changing analysis preset does not change the database request.
5. Changing record range does not change the charts request.
6. A record error leaves analysis visible; an analysis error leaves records visible.
7. Store change resets both ranges and closes mobile/admin dialogs.
8. An empty record range shows “暂无可查看记录” plus a “补记” action while analysis remains usable.
9. A delayed response from the old store/range never replaces the current store/range data.
10. Export requests use only `start` and `end`; an HTTP failure shows `导出失败，请重试` without changing filters/page/selection.
11. Delete/rollback success invalidates the current store's `database`, `charts`, ledger and home queries through the unchanged `invalidateUserData` helper.

- [ ] **Step 3: Run the new page test and confirm failure**

```sh
npm test -- src/pages/BusinessRecordsPage.test.tsx
```

Expected: FAIL because the page is not implemented.

- [ ] **Step 4: Implement page state and server query**

Keep independent state groups:

```ts
const [recordRange, setRecordRange] = useState<RecordRange>(() => currentMonthRange(today));
const [recordPage, setRecordPage] = useState(1);
const [selectedRecordId, setSelectedRecordId] = useState<number | null>(null);
const [mobileRecord, setMobileRecord] = useState<RecordSnapshot | null>(null);
```

Build the database request with fixed page size:

```ts
const params = new URLSearchParams({
  start: recordRange.start,
  end: recordRange.end,
  page: String(recordPage),
  page_size: "15",
});
```

On every successful page payload, preserve the selected ID only if it exists in the new items; otherwise select `items[0]?.id ?? null`. Do this in an effect keyed by `records.data?.items`, not during render.

Render `BusinessAnalysisCard` with `key={selected.id}` so a store change remounts the card and resets its independent analysis range without coupling it to record filters.

Implement export as a user-triggered blob request with `credentials: "include"`:

```ts
const handleExport = async () => {
  setExporting(true);
  setExportError("");
  let objectUrl: string | null = null;
  try {
    const exportParams = new URLSearchParams({
      start: recordRange.start,
      end: recordRange.end,
    });
    const response = await fetch(
      `/api/database/${selected.id}/export.xlsx?${exportParams.toString()}`,
      { credentials: "include" },
    );
    if (!response.ok) throw new Error("export failed");
    objectUrl = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = `营业记录-${recordRange.start}-${recordRange.end}.xlsx`;
    anchor.click();
  } catch {
    setExportError("导出失败，请重试");
  } finally {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    setExporting(false);
  }
};
```

Expose loading/failure state through `RecordFilters`. Do not include `page` or `page_size`, and do not mutate filter state from the export path.

- [ ] **Step 5: Implement desktop and mobile layout**

Use one semantic page heading, then this structural layout:

```tsx
<div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(22rem,24rem)] lg:items-start">
  <div className="min-w-0">
    <div className="hidden lg:block">{desktopTable}</div>
    <div className="overflow-x-hidden lg:hidden">{mobileList}</div>
  </div>
  <aside className="grid gap-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
    <div className="hidden lg:block">{desktopDetail}</div>
    <BusinessAnalysisCard key={selected.id} storeId={selected.id} today={today} />
  </aside>
</div>
```

Wrap the section in `mx-auto w-full max-w-7xl` so the two-column layout is not constrained by the old `max-w-4xl` calendar width.

Keep `MobileRecordSheet` outside the grid so it overlays correctly. Reuse the current audit/delete/rollback implementation with query invalidation unchanged.

- [ ] **Step 6: Point `/database` to the new page and remove old files**

Update only the `/database` lazy/import target now. Leave `/charts` temporarily available until Task 6 so focused migration tests can run independently. Delete the old calendar page and test after all management cases pass in the new file.

- [ ] **Step 7: Run page, related component, and build checks**

```sh
npm test -- src/pages/BusinessRecordsPage.test.tsx src/components/RecordDetailPanel.test.tsx src/components/BusinessAnalysisCard.test.tsx
npm run build
```

Expected: PASS.

- [ ] **Step 8: Commit the page migration**

```sh
git add frontend/src/pages/BusinessRecordsPage.tsx frontend/src/pages/BusinessRecordsPage.test.tsx frontend/src/router.tsx frontend/src/pages/DatabasePage.tsx frontend/src/pages/DatabasePage.test.tsx
git commit -m "feat: merge records and analysis page"
```

---

### Task 6: Remove the obsolete frontend charts chain

**Files:**
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/navigation/modules.ts`
- Modify: `frontend/src/pages/MorePage.tsx`
- Modify: `frontend/src/layouts/AppShell.tsx`
- Modify: `frontend/src/App.test.tsx`
- Delete: `frontend/src/pages/ChartsPage.tsx`
- Delete: `frontend/src/pages/ChartsPage.test.tsx`

- [ ] **Step 1: Change navigation tests first**

Update `App.test.tsx` to assert desktop navigation contains `营业记录` linking to `/database`, contains neither `历史记录` nor `经营分析`, and the mobile More page has no `/charts` link. Add a memory-router assertion that `/charts` renders the existing not-found route, proving no redirect was added.

- [ ] **Step 2: Run navigation tests and confirm old-link failures**

```sh
npm test -- src/App.test.tsx
```

Expected: FAIL because the old desktop and More links still exist.

- [ ] **Step 3: Delete only the frontend chain**

Remove the `ChartsPage` import and route, remove the two old desktop entries and replace them with one `营业记录` entry, remove the More-page link, remove the `/charts` icon mapping, and delete `ChartsPage.tsx` plus its test. Do not delete backend charts routes, schemas, service, query key, or API types.

- [ ] **Step 4: Prove there are no live frontend route references**

```sh
rg -n 'to="/charts"|path="charts"|ChartsPage|历史记录|经营分析' frontend/src
```

Expected: no route/import/navigation matches. Visible `经营分析` text inside `BusinessAnalysisCard` is allowed; inspect any remaining match rather than deleting blindly.

- [ ] **Step 5: Run tests/build and commit**

```sh
npm test -- src/App.test.tsx
npm test
npm run build
git add frontend/src/router.tsx frontend/src/navigation/modules.ts frontend/src/pages/MorePage.tsx frontend/src/layouts/AppShell.tsx frontend/src/App.test.tsx frontend/src/pages/ChartsPage.tsx frontend/src/pages/ChartsPage.test.tsx
git commit -m "refactor: remove obsolete charts page route"
```

Expected: PASS.

---

### Task 7: End-to-end and responsive acceptance

**Files:**
- Modify: `frontend/tests/daily-flow.spec.ts`
- Modify: `frontend/tests/responsive.spec.ts`

- [ ] **Step 1: Rewrite the failing merged-flow E2E test**

Replace the separate calendar/charts flow with one `/database` flow:

1. Open 营业记录.
2. Confirm 15-row page contract and descending dates.
3. Select a non-business row and verify right detail says `休息` or `天气停业`, never `营业`.
4. Change page and verify detail auto-selects the new first row without scrolling the page back manually.
5. Change analysis to `近 6 月`; verify records stay on the same page and the unified card changes its range/curve.
6. Verify both income groups, separator, and independent “查看全部” controls.
7. Verify `/charts` reaches not found.

- [ ] **Step 2: Rewrite responsive tests**

At desktop width, assert the record table and right rail are both visible, the rail computed `position` is sticky, and the analysis is below detail in the same rail.

At 320px, assert:

- document width equals viewport width;
- desktop table/detail are hidden;
- mobile list shows only date/status/revenue columns;
- clicking a row opens the bottom sheet with status, wash count, activity and edit/manage actions as permitted;
- analysis remains below the list after closing the sheet.

- [ ] **Step 3: Run the updated E2E tests and observe the initial failures**

```sh
npm run test:e2e -- tests/daily-flow.spec.ts tests/responsive.spec.ts
```

Expected: the first run may expose selector/layout defects; failures must point to a named acceptance rule above.

- [ ] **Step 4: Fix only acceptance defects in their owning files**

For each failure, add or tighten a unit/component regression test before changing implementation. Do not hide failures with arbitrary waits; wait on API responses or accessible UI state.

- [ ] **Step 5: Run full repository verification**

From `backend`:

```sh
ruff check .
pytest --cov=app --cov-report=term-missing
```

From `frontend`:

```sh
npm test
npm run build
npm run test:e2e
```

Expected: every command exits 0. Record the test counts and any coverage change in the handoff.

- [ ] **Step 6: Perform browser visual QA**

Use `browser:control-in-app-browser` against the local app and inspect at least:

- desktop current-month populated page;
- desktop page 2 with right detail visible;
- desktop empty record range with populated analysis;
- desktop analysis error with usable record table;
- 320px mobile list and open bottom sheet;
- both income groups expanded.

Check clipping, sticky behavior, independent scrolling, keyboard focus, visible selected row, status accuracy, and absence of horizontal overflow. Capture screenshots for any defect fixed during QA.

- [ ] **Step 7: Commit acceptance changes**

```sh
git add frontend/tests/daily-flow.spec.ts frontend/tests/responsive.spec.ts
git commit -m "test: cover merged business records experience"
```

If Step 4 changed an owning source or unit-test file, inspect `git status --short` and stage that exact path in the same commit; never stage unrelated worktree changes.

- [ ] **Step 8: Run `superpowers:verification-before-completion`**

Re-run the relevant commands required by that skill using fresh output. Do not claim completion from earlier cached runs.
