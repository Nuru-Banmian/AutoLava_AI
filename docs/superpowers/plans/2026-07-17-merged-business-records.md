# Merged Business Records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the separate history calendar and analytics page with one `/database` “营业记录” experience that combines a paginated record browser, selected-day details, and independently filtered business analysis on desktop and mobile.

**Architecture:** Keep the existing database, ledger, history, rollback, export, and charts API paths and React Query key roots. Extend charts additively with comparison metadata and snapshot-based included/excluded composition, then compose focused frontend components under `BusinessRecordsPage`; record-range state stays in the page while analysis-range state stays inside `BusinessAnalysisCard` and resets by store key.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async, MySQL, pytest, React 19, TypeScript, TanStack Query, date-fns, Recharts, Radix UI, Tailwind CSS, Vitest/Testing Library, MSW, Playwright.

## Global Constraints

- Merge `codex/management-center-optimization` before product-code changes; preserve its `AuthenticatedUser.is_owner`, user-management behavior, and current `invalidateUserData` semantics.
- Keep `/api/database/{resource}`, `/api/charts/{store_id}`, and `/api/ledger/{resource}` unchanged; API path cleanup is out of scope.
- Keep `databaseKey`, `chartsKey`, and `invalidateUserData` root-key semantics unchanged so income configuration publishing continues to invalidate records, analytics, ledger, and dashboard data.
- `/database` is the only frontend page for records and analytics; remove `/charts` without a redirect and delete `ChartsPage`.
- Record requests always send `page_size=15`, retain backend date-descending order, and never derive full-range totals or sorting from one client page.
- Record filters and analysis filters are independent. Store changes reset both to current month, record page to 1, selected record to the new page's first item, and all open detail/management overlays.
- Analysis `bucket` is optional at the API boundary with default `day` for compatibility; the new frontend always sends `day` or `month` explicitly.
- Composition uses persisted `DailyIncomeItem` snapshots (`category_name`, `include_in_total`, `sort_order`) and real item amounts. Never infer category amounts from total revenue.
- Legacy total-only records affect KPI totals, trends, and daily averages but never composition or `classified_included_total`.
- Included and excluded groups are ordered by snapshot `sort_order`, then category ID/name; each shows five rows initially and expands independently. Never synthesize an “其他” row.
- Desktop uses `minmax(0, 1fr) minmax(22rem, 24rem)` and a sticky, independently scrolling right rail. Mobile uses a fixed three-column list and bottom sheet with safe-area padding; neither surface may introduce horizontal scrolling.
- Use existing theme tokens and components; do not hard-code business colors.
- Every task follows red-green-refactor, runs its focused tests, and ends with a reviewable commit.

## File Responsibility Map

| File | Responsibility |
|---|---|
| `backend/app/schemas/charts.py` | Additive charts response models for range, comparison KPI, and excluded composition |
| `backend/app/api/routes/charts.py` | Query validation, explicit legacy category override validation, service call |
| `backend/app/services/analytics.py` | KPI/trend aggregation and snapshot-based composition for current/comparison ranges |
| `backend/tests/api/test_charts.py` | HTTP compatibility, query validation, stable JSON contract, store isolation |
| `backend/tests/services/test_analytics.py` | Snapshot grouping, ordering, archived items, legacy totals, comparison KPI |
| `frontend/src/lib/business-record-ranges.ts` | Pure record/analysis range resolution and chart query construction |
| `frontend/src/lib/business-record-ranges.test.ts` | Month-end, leap/short-month, 62-day threshold, comparison tests |
| `frontend/src/lib/business-record-export.ts` | Download current record range as XLSX and surface failures |
| `frontend/src/lib/business-record-export.test.ts` | Export URL, filename, blob cleanup, and HTTP failure tests |
| `frontend/src/api/types.ts` | TypeScript mirror of additive charts contract |
| `frontend/src/components/RecordFilters.tsx` | Record presets, custom dates, export action/status |
| `frontend/src/components/RecordPagination.tsx` | Shared fixed-size previous/next pagination |
| `frontend/src/components/RecordTable.tsx` | Desktop semantic four-column table, keyboard selection, loading/error/empty states |
| `frontend/src/components/MobileRecordList.tsx` | Mobile three-column record list and focusable row triggers |
| `frontend/src/components/RecordDetailPanel.tsx` | Complete selected-record details and role-gated actions |
| `frontend/src/components/MobileRecordSheet.tsx` | Accessible bottom-sheet container reusing `RecordDetailPanel` |
| `frontend/src/components/RecordManagementDialogs.tsx` | Admin history, delete, conflict reload, and rollback workflow |
| `frontend/src/components/ChartPanel.tsx` | Reusable chart renderer with embedded mode and stable empty state |
| `frontend/src/components/IncomeComposition.tsx` | Included/excluded rows, exact percentages, notes, independent expansion |
| `frontend/src/components/BusinessAnalysisCard.tsx` | Analysis range state, one charts query, KPI comparison, trend and composition |
| `frontend/src/pages/BusinessRecordsPage.tsx` | Store context, record query/selection, responsive layout, overlay coordination |
| `frontend/src/router.tsx` | Route `/database` to the merged page and remove `/charts` |
| `frontend/src/navigation/modules.ts` | One desktop “营业记录” entry |
| `frontend/src/pages/MorePage.tsx` | Remove mobile More analytics link |
| `frontend/src/layouts/AppShell.tsx` | Remove obsolete `/charts` icon mapping |
| `frontend/tests/daily-flow.spec.ts` | End-to-end merged record/analysis workflow |
| `frontend/tests/responsive.spec.ts` | Sticky desktop rail, 320px list/sheet, safe-area and overflow acceptance |

---

### Task 1: Synchronize the management-center baseline

**Files:**
- Merge source: `codex/management-center-optimization`
- Verify: `frontend/src/api/types.ts`
- Verify: `frontend/src/lib/user-api.ts`
- Verify: `frontend/src/pages/AdminPage.test.tsx`
- Verify: `frontend/src/pages/DatabasePage.test.tsx`

**Interfaces:**
- Consumes: branch `codex/management-center-optimization` at its reviewed tip.
- Produces: an implementation branch containing both the approved merged-records spec and management-center behavior, with clean backend/frontend baselines.

- [ ] **Step 1: Merge the reviewed management-center branch before editing product code**

```powershell
git status --short
git merge --no-edit codex/management-center-optimization
```

Expected: merge succeeds. If Git reports a conflict in a documentation file, keep both feature specs/plans; if it reports `frontend/src/api/types.ts`, retain `AuthenticatedUser.is_owner` and all existing ledger/database/chart types.

- [ ] **Step 2: Establish the dedicated backend test environment in the current terminal**

```powershell
$commonGitDir = git rev-parse --path-format=absolute --git-common-dir
$mainCheckout = Split-Path $commonGitDir -Parent
$databaseEnv = Join-Path $mainCheckout '.autolava-db.env'
$databaseLine = Get-Content $databaseEnv | Where-Object { $_ -like 'AUTOLAVA_DATABASE_URL=*' } | Select-Object -First 1
if (-not $databaseLine) { throw 'AUTOLAVA_DATABASE_URL is missing from .autolava-db.env' }
$databaseUrl = $databaseLine.Substring('AUTOLAVA_DATABASE_URL='.Length).Trim().Trim('"').Trim("'")
$env:AUTOLAVA_DATABASE_URL = & backend\.venv\Scripts\python.exe -c "import sys; from sqlalchemy.engine import make_url; print(make_url(sys.argv[1]).set(database='autolava_test').render_as_string(hide_password=False))" $databaseUrl
```

Expected: command returns without printing the database URL; the process environment points to the dedicated `autolava_test` database.

- [ ] **Step 3: Run both baselines after the merge**

```powershell
backend\.venv\Scripts\python.exe -m pytest -q backend\tests
npm test --prefix frontend
```

Expected: backend and frontend exit 0. Do not continue if the merge introduces a failing test.

- [ ] **Step 4: Verify invalidation and owner contracts explicitly**

```powershell
npm test --prefix frontend -- src/lib/user-api.test.ts src/pages/AdminPage.test.tsx src/pages/DatabasePage.test.tsx
rg -n 'AuthenticatedUser|is_owner|invalidateUserData|queryKey\[0\] === "database"|queryKey\[0\] === "charts"' frontend/src
```

Expected: focused tests pass; search shows owner typing and both database/charts invalidation branches.

- [ ] **Step 5: Commit only if conflict resolution created uncommitted changes**

```powershell
git status --short
git add docs frontend/src/api/types.ts frontend/src/pages/DatabasePage.test.tsx
git commit -m "chore: integrate management center baseline"
```

Expected: either a conflict-resolution commit is created or Git reports there is nothing additional to commit after the merge commit.

---

### Task 2: Extend the charts API with comparison and snapshot composition

**Files:**
- Modify: `backend/app/schemas/charts.py`
- Modify: `backend/app/api/routes/charts.py`
- Modify: `backend/app/services/analytics.py`
- Modify: `backend/tests/api/test_charts.py`
- Modify: `backend/tests/services/test_analytics.py`

**Interfaces:**
- Consumes: persisted `DailyIncomeItem.category_name`, `include_in_total`, `sort_order`, `amount`; optional legacy `category_id` query list.
- Produces: `AnalyticsService.calculate(store_id, start, end, category_ids=None, compare_start=None, compare_end=None, bucket="day") -> dict` and additive `ChartsResponse` fields `range`, `comparison_kpis`, `excluded_categories`, `classified_included_total`.

- [ ] **Step 1: Write failing service tests for snapshot grouping and legacy totals**

Add this focused test after updating `_seed_records` to populate snapshot fields on every `DailyIncomeItem`:

```python
session.add_all(
    [
        DailyIncomeItem(
            record_id=first.id,
            category_id=cash.id,
            category_name=cash.name,
            include_in_total=cash.include_in_total,
            sort_order=cash.sort_order,
            amount=Decimal("100.00"),
        ),
        DailyIncomeItem(
            record_id=first.id,
            category_id=card.id,
            category_name=card.name,
            include_in_total=card.include_in_total,
            sort_order=card.sort_order,
            amount=Decimal("50.00"),
        ),
        DailyIncomeItem(
            record_id=second.id,
            category_id=cash.id,
            category_name=cash.name,
            include_in_total=cash.include_in_total,
            sort_order=cash.sort_order,
            amount=Decimal("200.00"),
        ),
    ]
)
```

Likewise, change the API test `_record` item to copy `category.name`, `category.include_in_total`, and `category.sort_order` into the snapshot columns.

```python
async def test_snapshot_composition_preserves_groups_order_and_archived_names(
    db_session: AsyncSession,
) -> None:
    store, category_ids = await _seed_records(db_session, suffix="-composition")
    cash_id, card_id = category_ids
    records = list(
        await db_session.scalars(
            select(StoreDailyRecord)
            .where(StoreDailyRecord.store_id == store.id)
            .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
        )
    )
    archived = IncomeCategory(
        store_id=store.id,
        name="当前归档名称",
        include_in_total=False,
        is_active=False,
        sort_order=9,
    )
    db_session.add(archived)
    await db_session.flush()
    db_session.add(
        DailyIncomeItem(
            record_id=records[0].id,
            category_id=archived.id,
            category_name="历史优惠券",
            include_in_total=False,
            sort_order=0,
            amount=Decimal("7.00"),
        )
    )
    june = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 6, 10),
        daily_revenue=Decimal("80.00"),
        wash_count=None,
        is_open="营业",
        weather=None,
        weather_auto=None,
        weather_code=None,
        temperature_max=None,
        temperature_min=None,
        precipitation=None,
        activity=None,
        weather_edited=False,
        scanned=False,
        created_by=records[0].created_by,
        updated_by=records[0].updated_by,
    )
    db_session.add(june)
    await db_session.flush()

    result = await AnalyticsService(db_session).calculate(
        store_id=store.id,
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        category_ids=None,
        compare_start=date(2026, 6, 1),
        compare_end=date(2026, 6, 30),
        bucket="day",
    )

    assert [row["category_id"] for row in result["categories"]] == [cash_id, card_id]
    assert result["classified_included_total"] == "350.00"
    assert result["kpis"]["total_revenue"] == "350.00"
    assert result["excluded_categories"] == [
        {
            "category_id": archived.id,
            "category_name": "历史优惠券",
            "amount": "7.00",
        }
    ]
    assert result["comparison_kpis"] == {
        "start": "2026-06-01",
        "end": "2026-06-30",
        "total_revenue": "80.00",
        "open_days": 1,
        "average_revenue": "80.00",
    }
```

Extend the total-only test with exact additive assertions:

```python
assert result["classified_included_total"] == "0.00"
assert result["categories"] == []
assert result["excluded_categories"] == []
```

- [ ] **Step 2: Run the service tests and verify the contract is red**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/services/test_analytics.py -q
```

Expected: FAIL because `calculate` does not accept comparison/bucket arguments and does not return the additive fields.

- [ ] **Step 3: Write failing API compatibility and validation tests**

Add these cases to `backend/tests/api/test_charts.py`:

```python
async def test_charts_defaults_bucket_and_comparison_for_existing_callers(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31"
    )
    assert response.status_code == 200
    assert response.json()["range"] == {
        "start": "2026-07-01",
        "end": "2026-07-31",
        "bucket": "day",
    }
    assert response.json()["comparison_kpis"] is None


async def test_charts_requires_a_complete_valid_comparison_pair(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    base = f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31"
    missing_end = await auth_client.get(base + "&compare_start=2026-06-01")
    missing_start = await auth_client.get(base + "&compare_end=2026-06-30")
    reversed_range = await auth_client.get(
        base + "&compare_start=2026-06-30&compare_end=2026-06-01"
    )
    assert [missing_end.status_code, missing_start.status_code, reversed_range.status_code] == [
        422,
        422,
        422,
    ]


async def test_charts_accepts_month_bucket_and_returns_excluded_snapshot_items(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    excluded = IncomeCategory(
        store_id=store.id,
        name="当前名称",
        include_in_total=False,
        is_active=False,
        sort_order=3,
    )
    db_session.add(excluded)
    await db_session.flush()
    await _record(db_session, store, excluded)
    item = await db_session.scalar(
        select(DailyIncomeItem).where(DailyIncomeItem.category_id == excluded.id)
    )
    assert item is not None
    item.category_name = "历史优惠券"
    item.include_in_total = False
    item.sort_order = 1
    await db_session.flush()

    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31&bucket=month"
    )

    assert response.status_code == 200
    assert response.json()["range"]["bucket"] == "month"
    assert response.json()["categories"] == []
    assert response.json()["excluded_categories"] == [
        {
            "category_id": excluded.id,
            "category_name": "历史优惠券",
            "amount": "25.00",
        }
    ]
```

Update `test_charts_returns_stable_empty_result` to require:

```python
"range": {"start": "2026-07-01", "end": "2026-07-31", "bucket": "day"},
"comparison_kpis": None,
"classified_included_total": "0.00",
"excluded_categories": [],
```

Keep the existing explicit excluded `category_id` test unchanged; it is the compatibility guard.

- [ ] **Step 4: Run API tests and verify the new fields/validation are red**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/api/test_charts.py -q
```

Expected: FAIL on absent response fields and absent pair validation while existing authentication/store tests remain green.

- [ ] **Step 5: Add exact Pydantic response models**

Add to `backend/app/schemas/charts.py`:

```python
from typing import Literal


class ChartRange(BaseModel):
    start: str
    end: str
    bucket: Literal["day", "month"]


class ChartComparisonKpis(BaseModel):
    start: str
    end: str
    total_revenue: str
    open_days: int
    average_revenue: str
```

Replace only the `ChartsResponse` declaration with:

```python
class ChartsResponse(BaseModel):
    kpis: ChartKpis
    range: ChartRange
    comparison_kpis: ChartComparisonKpis | None
    classified_included_total: str
    daily: list[DailyRevenue]
    categories: list[CategoryComposition]
    excluded_categories: list[CategoryComposition]
    monthly: list[MonthlyRevenue]
    weather: list[WeatherRevenue]
    weekday: list[WeekdayRevenue]
```

- [ ] **Step 6: Implement route parameters and validation without changing paths**

Import `Literal` and change the route signature/validation to:

```python
async def get_charts(
    start: date,
    end: date,
    session: Session,
    access: Annotated[StoreAccess, Depends(require_store_access)],
    category_id: Annotated[list[int] | None, Query()] = None,
    compare_start: date | None = None,
    compare_end: date | None = None,
    bucket: Literal["day", "month"] = "day",
) -> ChartsResponse:
    if start > end:
        raise HTTPException(422, "start must be on or before end")
    if (compare_start is None) != (compare_end is None):
        raise HTTPException(422, "compare_start and compare_end must be provided together")
    if compare_start is not None and compare_end is not None and compare_start > compare_end:
        raise HTTPException(422, "compare_start must be on or before compare_end")

    selected_ids = None if category_id is None else list(dict.fromkeys(category_id))
    if selected_ids is not None:
        owned_ids = set(
            await session.scalars(
                select(IncomeCategory.id).where(
                    IncomeCategory.store_id == access.store.id,
                    IncomeCategory.id.in_(selected_ids),
                )
            )
        )
        if owned_ids != set(selected_ids):
            raise HTTPException(422, "All categories must belong to the requested store")

    result = await AnalyticsService(session).calculate(
        store_id=access.store.id,
        start=start,
        end=end,
        category_ids=selected_ids,
        compare_start=compare_start,
        compare_end=compare_end,
        bucket=bucket,
    )
    return ChartsResponse.model_validate(result)
```

- [ ] **Step 7: Implement snapshot composition and comparison KPI**

Use this exact public signature:

```python
async def calculate(
    self,
    *,
    store_id: int,
    start: date,
    end: date,
    category_ids: list[int] | None,
    compare_start: date | None = None,
    compare_end: date | None = None,
    bucket: Literal["day", "month"] = "day",
) -> dict:
```

Introduce an immutable aggregation key and helper:

```python
@dataclass(frozen=True)
class CompositionKey:
    category_id: int
    category_name: str
    include_in_total: bool
    sort_order: int


def _composition_rows(totals: dict[CompositionKey, Decimal]) -> list[dict]:
    return [
        {
            "category_id": key.category_id,
            "category_name": key.category_name,
            "amount": _money(amount),
        }
        for key, amount in sorted(
            totals.items(),
            key=lambda row: (
                row[0].sort_order,
                row[0].category_id,
                row[0].category_name,
            ),
        )
    ]
```

For each item, build `CompositionKey` from the item snapshot, add it to included/excluded totals, and separately add it to legacy-selected totals when `category_ids is None and item.include_in_total` or its ID is explicitly selected:

```python
selected_ids = None if category_ids is None else set(category_ids)
included_totals: dict[CompositionKey, Decimal] = defaultdict(lambda: Decimal("0.00"))
excluded_totals: dict[CompositionKey, Decimal] = defaultdict(lambda: Decimal("0.00"))
selected_totals: dict[CompositionKey, Decimal] = defaultdict(lambda: Decimal("0.00"))
for record in records:
    for item in record.items:
        key = CompositionKey(
            category_id=item.category_id,
            category_name=item.category_name,
            include_in_total=item.include_in_total,
            sort_order=item.sort_order,
        )
        if item.include_in_total:
            included_totals[key] += item.amount
        else:
            excluded_totals[key] += item.amount
        if selected_ids is not None and item.category_id in selected_ids:
            selected_totals[key] += item.amount
```

Then set:

```python
included_rows = _composition_rows(included_totals)
excluded_rows = _composition_rows(excluded_totals)
category_rows = included_rows if category_ids is None else _composition_rows(selected_totals)
classified_included_total = sum(included_totals.values(), Decimal("0.00"))
```

Extract KPI computation into a helper used for current and comparison records. Return comparison only when both comparison dates are present, and add:

```python
"range": {"start": start.isoformat(), "end": end.isoformat(), "bucket": bucket},
"comparison_kpis": comparison_kpis,
"classified_included_total": _money(classified_included_total),
"excluded_categories": excluded_rows,
```

Retain existing `daily`, `monthly`, `weather`, `weekday`, wash metrics, primary-category tie-break, and monetary rounding behavior.

- [ ] **Step 8: Run focused/full backend verification and commit**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/services/test_analytics.py backend/tests/api/test_charts.py -q
backend\.venv\Scripts\ruff.exe check backend/app backend/tests
backend\.venv\Scripts\python.exe -m pytest backend/tests -q
git add backend/app/schemas/charts.py backend/app/api/routes/charts.py backend/app/services/analytics.py backend/tests/api/test_charts.py backend/tests/services/test_analytics.py
git commit -m "feat: extend business analytics contract"
```

Expected: all backend tests pass; commit contains no database path/schema migration.

---

### Task 3: Define record and analysis ranges as pure functions

**Files:**
- Create: `frontend/src/lib/business-record-ranges.ts`
- Create: `frontend/src/lib/business-record-ranges.test.ts`
- Modify: `frontend/src/api/types.ts`

**Interfaces:**
- Consumes: store-local `today` as `yyyy-MM-dd`.
- Produces: `recordRange(mode, today, custom?)`, `analysisRange(mode, today, custom?)`, `analysisSearchParams(range)`, and additive chart response types.

- [ ] **Step 1: Write failing date-range tests with exact boundaries**

Create `frontend/src/lib/business-record-ranges.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { analysisRange, analysisSearchParams, recordRange } from "@/lib/business-record-ranges";

describe("business record ranges", () => {
  it("uses full calendar months for record browsing", () => {
    expect(recordRange("current-month", "2026-07-17")).toEqual({ start: "2026-07-01", end: "2026-07-31" });
    expect(recordRange("previous-month", "2026-01-10")).toEqual({ start: "2025-12-01", end: "2025-12-31" });
  });

  it("compares month-to-date with the same available prior-month period", () => {
    expect(analysisRange("current-month", "2026-03-31")).toEqual({
      start: "2026-03-01",
      end: "2026-03-31",
      compareStart: "2026-02-01",
      compareEnd: "2026-02-28",
      bucket: "day",
    });
  });

  it("uses full previous months and a six-month shifted comparison", () => {
    expect(analysisRange("previous-month", "2026-03-17")).toEqual({
      start: "2026-02-01",
      end: "2026-02-28",
      compareStart: "2026-01-01",
      compareEnd: "2026-01-31",
      bucket: "day",
    });
    expect(analysisRange("six-months", "2026-02-10")).toEqual({
      start: "2025-09-01",
      end: "2026-02-10",
      compareStart: "2025-03-01",
      compareEnd: "2025-08-10",
      bucket: "month",
    });
    expect(analysisRange("six-months", "2026-08-31").compareEnd).toBe("2026-02-28");
  });

  it("switches custom aggregation after 62 inclusive days and omits comparison", () => {
    expect(analysisRange("custom", "2026-07-17", { start: "2026-01-01", end: "2026-03-03" }).bucket).toBe("day");
    expect(analysisRange("custom", "2026-07-17", { start: "2026-01-01", end: "2026-03-04" })).toMatchObject({
      compareStart: null,
      compareEnd: null,
      bucket: "month",
    });
    expect(() => analysisRange("custom", "2026-07-17", { start: "2026-07-18", end: "2026-07-17" })).toThrow(RangeError);
  });

  it("serializes comparison only when present", () => {
    const params = analysisSearchParams(analysisRange("current-month", "2026-07-17"));
    expect(params.toString()).toBe("start=2026-07-01&end=2026-07-17&bucket=day&compare_start=2026-06-01&compare_end=2026-06-17");
  });
});
```

- [ ] **Step 2: Run the range tests and verify the missing module failure**

```powershell
npm test --prefix frontend -- src/lib/business-record-ranges.test.ts
```

Expected: FAIL because `business-record-ranges.ts` does not exist.

- [ ] **Step 3: Implement the complete pure range module**

Create `frontend/src/lib/business-record-ranges.ts` with exported types and functions:

```ts
import { differenceInCalendarDays, endOfMonth, format, parseISO, startOfMonth, subMonths } from "date-fns";
import type { ChartBucket } from "@/api/types";

export type RecordRangeMode = "current-month" | "previous-month" | "custom";
export type AnalysisRangeMode = "current-month" | "previous-month" | "six-months" | "custom";
export interface DateRange { start: string; end: string }
export interface ResolvedAnalysisRange extends DateRange {
  compareStart: string | null;
  compareEnd: string | null;
  bucket: ChartBucket;
}

const iso = (value: Date) => format(value, "yyyy-MM-dd");
const validate = (range: DateRange) => {
  if (!range.start || !range.end || parseISO(range.start) > parseISO(range.end)) {
    throw new RangeError("start must be on or before end");
  }
  return range;
};

export function recordRange(mode: RecordRangeMode, today: string, custom?: DateRange): DateRange {
  const now = parseISO(today);
  if (mode === "custom") return validate(custom ?? { start: "", end: "" });
  const target = mode === "current-month" ? now : subMonths(now, 1);
  return { start: iso(startOfMonth(target)), end: iso(endOfMonth(target)) };
}

export function analysisRange(mode: AnalysisRangeMode, today: string, custom?: DateRange): ResolvedAnalysisRange {
  const now = parseISO(today);
  if (mode === "custom") {
    const range = validate(custom ?? { start: "", end: "" });
    const inclusiveDays = differenceInCalendarDays(parseISO(range.end), parseISO(range.start)) + 1;
    return { ...range, compareStart: null, compareEnd: null, bucket: inclusiveDays <= 62 ? "day" : "month" };
  }
  if (mode === "current-month") {
    return {
      start: iso(startOfMonth(now)),
      end: today,
      compareStart: iso(startOfMonth(subMonths(now, 1))),
      compareEnd: iso(subMonths(now, 1)),
      bucket: "day",
    };
  }
  if (mode === "previous-month") {
    const previous = subMonths(now, 1);
    const comparison = subMonths(now, 2);
    return {
      start: iso(startOfMonth(previous)),
      end: iso(endOfMonth(previous)),
      compareStart: iso(startOfMonth(comparison)),
      compareEnd: iso(endOfMonth(comparison)),
      bucket: "day",
    };
  }
  return {
    start: iso(startOfMonth(subMonths(now, 5))),
    end: today,
    compareStart: iso(startOfMonth(subMonths(now, 11))),
    compareEnd: iso(subMonths(now, 6)),
    bucket: "month",
  };
}

export function analysisSearchParams(range: ResolvedAnalysisRange): URLSearchParams {
  const params = new URLSearchParams({ start: range.start, end: range.end, bucket: range.bucket });
  if (range.compareStart && range.compareEnd) {
    params.set("compare_start", range.compareStart);
    params.set("compare_end", range.compareEnd);
  }
  return params;
}
```

- [ ] **Step 4: Add exact TypeScript response types**

In `frontend/src/api/types.ts`, introduce reusable chart types and replace the inline `ChartsResponse` declaration:

```ts
export type ChartBucket = "day" | "month";
export interface CategoryComposition { category_id: number; category_name: string; amount: string }
export interface ChartComparisonKpis { start: string; end: string; total_revenue: string; open_days: number; average_revenue: string }
export interface ChartsResponse {
  kpis: { total_revenue: string; record_days: number; open_days: number; average_revenue: string; primary_categories: CategoryComposition[]; total_wash_count: number | null; average_ticket: string | null };
  range: { start: string; end: string; bucket: ChartBucket };
  comparison_kpis: ChartComparisonKpis | null;
  classified_included_total: string;
  daily: { date: string; revenue: string }[];
  categories: CategoryComposition[];
  excluded_categories: CategoryComposition[];
  monthly: { month: string; revenue: string }[];
  weather: { weather: string; average_revenue: string }[];
  weekday: { weekday: number; average_revenue: string }[];
}
```

Keep `ChartBucket` imported from `@/api/types` in the range module; do not declare a second copy.

- [ ] **Step 5: Run tests/build and commit**

```powershell
npm test --prefix frontend -- src/lib/business-record-ranges.test.ts
npm run build --prefix frontend
git add frontend/src/lib/business-record-ranges.ts frontend/src/lib/business-record-ranges.test.ts frontend/src/api/types.ts
git commit -m "feat: define business record date ranges"
```

Expected: range tests and TypeScript build pass.

---

### Task 4: Implement record export with observable failure state

**Files:**
- Create: `frontend/src/lib/business-record-export.ts`
- Create: `frontend/src/lib/business-record-export.test.ts`

**Interfaces:**
- Consumes: `storeId: number`, `DateRange`, browser `fetch`, `Blob`, and object URLs.
- Produces: `downloadBusinessRecords(storeId, range): Promise<void>`; rejects with `ApiError` on non-2xx responses.

- [ ] **Step 1: Write failing export tests**

Create `frontend/src/lib/business-record-export.test.ts` with MSW and browser URL spies:

```ts
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";
import { downloadBusinessRecords } from "@/lib/business-record-export";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { server.resetHandlers(); vi.restoreAllMocks(); });
afterAll(() => server.close());

it("downloads exactly the active range and revokes the object URL", async () => {
  let requested = "";
  server.use(http.get("/api/database/7/export.xlsx", ({ request }) => {
    requested = request.url;
    return new HttpResponse(new Blob(["xlsx"]), { status: 200 });
  }));
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:records");
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  const click = vi.fn();
  vi.spyOn(document, "createElement").mockReturnValue({ href: "", download: "", click } as unknown as HTMLAnchorElement);

  await downloadBusinessRecords(7, { start: "2026-07-01", end: "2026-07-31" });

  expect(new URL(requested).search).toBe("?start=2026-07-01&end=2026-07-31");
  expect(click).toHaveBeenCalledOnce();
  expect(revoke).toHaveBeenCalledWith("blob:records");
});

it("rejects a failed export without creating a download", async () => {
  server.use(http.get("/api/database/7/export.xlsx", () => HttpResponse.json({ detail: "failed" }, { status: 500 })));
  const create = vi.spyOn(URL, "createObjectURL");
  await expect(downloadBusinessRecords(7, { start: "2026-07-01", end: "2026-07-31" })).rejects.toMatchObject({ status: 500 });
  expect(create).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run tests and verify the module is missing**

```powershell
npm test --prefix frontend -- src/lib/business-record-export.test.ts
```

Expected: FAIL because the export module does not exist.

- [ ] **Step 3: Implement the download helper**

Create `frontend/src/lib/business-record-export.ts`:

```ts
import { ApiError } from "@/api/client";
import type { DateRange } from "@/lib/business-record-ranges";

export async function downloadBusinessRecords(storeId: number, range: DateRange): Promise<void> {
  const params = new URLSearchParams({ start: range.start, end: range.end });
  const response = await fetch(`/api/database/${storeId}/export.xlsx?${params.toString()}`, { credentials: "include" });
  if (!response.ok) throw new ApiError(response.status, "导出失败，请重试");
  const objectUrl = URL.createObjectURL(await response.blob());
  try {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = `营业记录-${range.start}-${range.end}.xlsx`;
    anchor.click();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
```

- [ ] **Step 4: Run tests and commit**

```powershell
npm test --prefix frontend -- src/lib/business-record-export.test.ts
git add frontend/src/lib/business-record-export.ts frontend/src/lib/business-record-export.test.ts
git commit -m "feat: download filtered business records"
```

Expected: both export tests pass.

---

### Task 5: Build record browsing primitives

**Files:**
- Create: `frontend/src/components/RecordFilters.tsx`
- Create: `frontend/src/components/RecordFilters.test.tsx`
- Create: `frontend/src/components/RecordPagination.tsx`
- Create: `frontend/src/components/RecordPagination.test.tsx`
- Create: `frontend/src/components/RecordTable.tsx`
- Create: `frontend/src/components/RecordTable.test.tsx`
- Create: `frontend/src/components/MobileRecordList.tsx`
- Create: `frontend/src/components/MobileRecordList.test.tsx`

**Interfaces:**
- Consumes: `DateRange`, `RecordRangeMode`, `RecordSnapshot[]`, fixed page size 15.
- Produces: controlled filters, shared pagination, desktop semantic table, mobile list, and `onSelect(record, trigger)` callbacks.

- [ ] **Step 1: Write failing filter and pagination tests**

Tests must assert the controlled contract:

```tsx
render(<RecordFilters mode="current-month" range={{ start: "2026-07-01", end: "2026-07-31" }} today="2026-07-17" exporting={false} exportError="" onChange={onChange} onExport={onExport} />);
expect(screen.getByRole("button", { name: "本月" })).toHaveAttribute("aria-pressed", "true");
fireEvent.click(screen.getByRole("button", { name: "上月" }));
expect(onChange).toHaveBeenCalledWith("previous-month", { start: "2026-06-01", end: "2026-06-30" });
fireEvent.click(screen.getByRole("button", { name: "导出当前范围" }));
expect(onExport).toHaveBeenCalledOnce();
```

```tsx
render(<RecordPagination page={2} total={31} pageSize={15} onPageChange={onPageChange} />);
expect(screen.getByText("第 2 / 3 页")).toBeInTheDocument();
fireEvent.click(screen.getByRole("button", { name: "下一页" }));
expect(onPageChange).toHaveBeenCalledWith(3);
```

Also assert custom invalid dates do not call `onChange`, exporting disables the button, and `exportError="导出失败，请重试"` renders `role="alert"`.

- [ ] **Step 2: Write failing desktop/mobile record tests**

Use a `休息` fixture and assert:

```tsx
render(<RecordTable records={[record]} selectedId={record.id} loading={false} error={null} onSelect={onSelect} onRetry={onRetry} />);
expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["日期", "状态", "总营业额", "天气"]);
const row = screen.getByRole("row", { name: /2026年7月14日 休息/ });
expect(row).toHaveAttribute("aria-selected", "true");
fireEvent.keyDown(row, { key: "Enter" });
expect(onSelect).toHaveBeenCalledWith(record);
```

```tsx
render(<MobileRecordList records={[record]} selectedId={null} onSelect={onSelect} />);
expect(screen.getByRole("button", { name: /2026年7月14日，休息，€100.00/ })).toBeInTheDocument();
expect(screen.queryByText("晴")).not.toBeInTheDocument();
```

Add loading skeleton, error/retry, empty state, visible text status marker, Space-key activation, and “no dynamic income/wash/activity columns” assertions.

- [ ] **Step 3: Run the component tests and verify they are red**

```powershell
npm test --prefix frontend -- src/components/RecordFilters.test.tsx src/components/RecordPagination.test.tsx src/components/RecordTable.test.tsx src/components/MobileRecordList.test.tsx
```

Expected: FAIL because the four components do not exist.

- [ ] **Step 4: Implement exact component contracts**

Use these props:

```ts
interface RecordFiltersProps {
  mode: RecordRangeMode;
  range: DateRange;
  today: string;
  exporting: boolean;
  exportError: string;
  onChange(mode: RecordRangeMode, range: DateRange): void;
  onExport(): void;
}

interface RecordPaginationProps {
  page: number;
  total: number;
  pageSize: 15;
  onPageChange(page: number): void;
}

interface RecordTableProps {
  records: RecordSnapshot[];
  selectedId: number | null;
  loading: boolean;
  error: Error | null;
  onSelect(record: RecordSnapshot): void;
  onRetry(): void;
}

interface MobileRecordListProps {
  records: RecordSnapshot[];
  selectedId: number | null;
  onSelect(record: RecordSnapshot, trigger: HTMLButtonElement): void;
}
```

In `RecordTable`, render real `table`, `thead`, `tbody`, and `tr aria-selected`. Give each data row `tabIndex={0}` and use one activation function for click, Enter, and Space:

```ts
function activateFromKeyboard(event: React.KeyboardEvent<HTMLTableRowElement>, record: RecordSnapshot) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  onSelect(record);
}
```

Apply selected-row and status-marker styling with theme tokens:

```tsx
<tr
  aria-selected={record.id === selectedId}
  className={record.id === selectedId ? "border-l-4 border-primary bg-primary/10" : "border-l-4 border-transparent"}
>
  <td>{dateLabel}</td>
  <td><span aria-hidden="true" className="mr-2 inline-block size-2 rounded-full bg-current" />{record.is_open}</td>
</tr>
```

Implement preset and pagination calculations exactly:

```ts
const choosePreset = (next: Exclude<RecordRangeMode, "custom">) => onChange(next, recordRange(next, today));
const [customDraft, setCustomDraft] = useState<DateRange>(range);
const updateCustom = (patch: Partial<DateRange>) => {
  const next = { ...customDraft, ...patch };
  setCustomDraft(next);
  if (next.start && next.end && next.start <= next.end && next.end <= today) {
    onChange("custom", next);
  }
};
const totalPages = Math.max(1, Math.ceil(total / pageSize));
const previousDisabled = page <= 1;
const nextDisabled = page >= totalPages;
```

In `MobileRecordList`, render each row as:

```tsx
<button
  type="button"
  className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 overflow-hidden px-3 py-3 text-left"
  aria-label={`${dateLabel}，${record.is_open}，${formatMoney(record.daily_revenue)}`}
  onClick={(event) => onSelect(record, event.currentTarget)}
>
  <span className="truncate">{dateLabel}</span>
  <span className="whitespace-nowrap">{record.is_open}</span>
  <span className="whitespace-nowrap text-right">{formatMoney(record.daily_revenue)}</span>
</button>
```

Use `role="status"` for skeleton/loading and `role="alert"` plus named retry button for errors.

- [ ] **Step 5: Run focused tests/build and commit**

```powershell
npm test --prefix frontend -- src/components/RecordFilters.test.tsx src/components/RecordPagination.test.tsx src/components/RecordTable.test.tsx src/components/MobileRecordList.test.tsx
npm run build --prefix frontend
git add frontend/src/components/RecordFilters.tsx frontend/src/components/RecordFilters.test.tsx frontend/src/components/RecordPagination.tsx frontend/src/components/RecordPagination.test.tsx frontend/src/components/RecordTable.tsx frontend/src/components/RecordTable.test.tsx frontend/src/components/MobileRecordList.tsx frontend/src/components/MobileRecordList.test.tsx
git commit -m "feat: add responsive record browser components"
```

Expected: focused tests and build pass.

---

### Task 6: Extract complete record details and management workflows

**Files:**
- Create: `frontend/src/components/RecordDetailPanel.tsx`
- Create: `frontend/src/components/RecordDetailPanel.test.tsx`
- Create: `frontend/src/components/MobileRecordSheet.tsx`
- Create: `frontend/src/components/MobileRecordSheet.test.tsx`
- Create: `frontend/src/components/RecordManagementDialogs.tsx`
- Create: `frontend/src/components/RecordManagementDialogs.test.tsx`
- Delete: `frontend/src/components/RecordDetail.tsx`

**Interfaces:**
- Consumes: `RecordSnapshot`, role capabilities, store ID, QueryClient invalidation, exact triggering element.
- Produces: reusable complete detail content, focus-restoring mobile sheet, and isolated admin delete/audit/rollback dialogs.

- [ ] **Step 1: Write failing detail/status tests**

Create tests that render `RecordDetailPanel` for `营业`, `休息`, and `天气停业`. The `休息` case must assert:

```tsx
render(<RecordDetailPanel record={{ ...record, is_open: "休息", wash_count: 0, activity: "会员日" }} canEdit canManage={false} onManage={vi.fn()} />);
expect(screen.getByText("休息", { exact: true })).toBeInTheDocument();
expect(screen.queryByText("营业", { exact: true })).not.toBeInTheDocument();
expect(screen.getByText("洗车数量 0")).toBeInTheDocument();
expect(screen.getByText(/会员日/)).toBeInTheDocument();
expect(screen.getByText("计入总营业额")).toBeInTheDocument();
expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-14");
```

Assert ordinary users have no manage button and legacy records show “历史记录仅保存营业额总计”.

- [ ] **Step 2: Write failing mobile focus/safe-area tests**

Render a trigger button and controlled `MobileRecordSheet`; open, close, and assert the exact trigger regains focus. Assert the sheet has an accessible date title, dialog semantics, `RecordDetailPanel` content, and a class containing `safe-area-inset-bottom`.

- [ ] **Step 3: Port management regressions into a focused component test**

Move the behavior assertions from `DatabasePage.test.tsx` into `RecordManagementDialogs.test.tsx` and keep exact coverage for:

```ts
expect(new URL(deleteRequest).search).toBe("?expected_version=1");
expect(await screen.findByRole("button", { name: "回滚 #9" })).toBeInTheDocument();
expect(screen.getByRole("alert")).toHaveTextContent("数据已经发生变化，请刷新后重试");
expect(invalidatedRoots).toEqual(expect.arrayContaining(["ledger", "database", "charts", "dashboard"]));
```

Also assert non-admin rendering exposes no delete, history, or rollback operation.

- [ ] **Step 4: Run tests and verify extraction is red**

```powershell
npm test --prefix frontend -- src/components/RecordDetailPanel.test.tsx src/components/MobileRecordSheet.test.tsx src/components/RecordManagementDialogs.test.tsx
```

Expected: FAIL because the extracted components do not exist.

- [ ] **Step 5: Implement the detail and sheet contracts**

Use:

```ts
interface RecordDetailPanelProps {
  record: RecordSnapshot;
  canEdit: boolean;
  canManage: boolean;
  onManage(): void;
}

interface MobileRecordSheetProps extends RecordDetailPanelProps {
  open: boolean;
  returnFocusTo: HTMLButtonElement | null;
  onOpenChange(open: boolean): void;
}
```

Move the existing detail markup into `RecordDetailPanel`, add a text-and-dot status treatment, and show each composed item with `item.include_in_total ? "计入总营业额" : "独立记录"`.

Implement sheet content with:

```tsx
<SheetContent
  side="bottom"
  className="max-h-[90vh] overflow-y-auto rounded-t-2xl p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]"
  onCloseAutoFocus={(event) => {
    event.preventDefault();
    returnFocusTo?.focus();
  }}
>
  <SheetTitle className="sr-only">{record.date} 营业记录详情</SheetTitle>
  <RecordDetailPanel record={record} canEdit={canEdit} canManage={canManage} onManage={onManage} />
</SheetContent>
```

- [ ] **Step 6: Implement management workflow with stale-scope guards**

Use this external contract:

```ts
interface RecordManagementDialogsProps {
  storeId: number;
  record: RecordSnapshot | null;
  targetDate: string | null;
  open: boolean;
  onOpenChange(open: boolean): void;
  onCompleted(): void;
}
```

Move history query, delete mutation, 409 reload, rollback mutation, and confirmation dialogs from `DatabasePage`. Capture mutation `storeId`/date/version in variables; before showing messages, verify they still match current props. On success call `invalidateUserData(client, variables.storeId)` and invalidate `['database','history',variables.storeId]`.

- [ ] **Step 7: Run tests/build and commit**

```powershell
npm test --prefix frontend -- src/components/RecordDetailPanel.test.tsx src/components/MobileRecordSheet.test.tsx src/components/RecordManagementDialogs.test.tsx
npm run build --prefix frontend
git add frontend/src/components/RecordDetail.tsx frontend/src/components/RecordDetailPanel.tsx frontend/src/components/RecordDetailPanel.test.tsx frontend/src/components/MobileRecordSheet.tsx frontend/src/components/MobileRecordSheet.test.tsx frontend/src/components/RecordManagementDialogs.tsx frontend/src/components/RecordManagementDialogs.test.tsx
git commit -m "refactor: extract record detail management flows"
```

Expected: focused tests/build pass and `RecordDetail.tsx` is deleted.

---

### Task 7: Build composition and embedded chart presentation

**Files:**
- Modify: `frontend/src/components/ChartPanel.tsx`
- Modify: `frontend/src/components/ChartPanel.test.tsx`
- Create: `frontend/src/components/IncomeComposition.tsx`
- Create: `frontend/src/components/IncomeComposition.test.tsx`

**Interfaces:**
- Consumes: chart rows with raw money strings; included/excluded `CategoryComposition[]`; current total and classified included total.
- Produces: `ChartPanel` with `embedded?: boolean`, and `IncomeComposition` with exact-cent percentages and independent group expansion.

- [ ] **Step 1: Write failing embedded-chart and composition tests**

Extend `ChartPanel.test.tsx` with a rendered component:

```tsx
render(<ChartPanel embedded title="营业额趋势" kind="line" data={[{ label: "7月1日", revenue: 100, revenue_raw: "100.00" }]} xKey="label" valueKey="revenue" />);
expect(screen.getByRole("heading", { name: "营业额趋势" })).toBeInTheDocument();
expect(screen.getByTestId("chart-panel-content").closest("[data-slot='card']")).toBeNull();
```

Create composition tests with six included and six excluded rows. Assert only five from each group are initially visible, `50.0%` uses `classifiedIncludedTotal`, excluded rows contain no percent, and expanding included does not expose excluded row six. Add single-category and zero-classified-total cases that render no proportion bar.

- [ ] **Step 2: Run focused tests and verify they are red**

```powershell
npm test --prefix frontend -- src/components/ChartPanel.test.tsx src/components/IncomeComposition.test.tsx
```

Expected: FAIL because `embedded` and `IncomeComposition` do not exist.

- [ ] **Step 3: Add embedded mode without removing existing chart kinds**

Extend props:

```ts
interface ChartPanelProps {
  title: string;
  data?: Record<string, unknown>[];
  kind?: ChartKind;
  xKey?: string;
  valueKey?: string;
  children?: ReactNode;
  embedded?: boolean;
  emptyMessage?: string;
}
```

Build `header` and `content` once. Return `<>{header}{content}</>` when `embedded` and the existing `Card` wrapper otherwise. Put `data-testid="chart-panel-content"` on the content container and use `emptyMessage ?? "暂无数据"`.

- [ ] **Step 4: Implement exact percentage helpers and group rendering**

Create `IncomeComposition.tsx` with:

```ts
export function compositionPercentage(amount: string, total: string): string {
  const amountCents = amountToCents(amount) ?? 0n;
  const totalCents = amountToCents(total) ?? 0n;
  if (totalCents <= 0n) return "0.0%";
  const tenths = (amountCents * 1000n + totalCents / 2n) / totalCents;
  return `${tenths / 10n}.${tenths % 10n}%`;
}

interface IncomeCompositionProps {
  included: CategoryComposition[];
  excluded: CategoryComposition[];
  classifiedIncludedTotal: string;
  totalRevenue: string;
}
```

Maintain `includedExpanded` and `excludedExpanded` separately. Render percentage bars only when `included.length >= 2` and `classifiedIncludedTotal > 0`; every row always shows name and formatted amount. Put an `<hr>` between groups, explain excluded amounts do not enter total/delta/average, and when classified total is lower than total revenue explain that historical total-only records were not assigned to categories.

- [ ] **Step 5: Run tests/build and commit**

```powershell
npm test --prefix frontend -- src/components/ChartPanel.test.tsx src/components/IncomeComposition.test.tsx
npm run build --prefix frontend
git add frontend/src/components/ChartPanel.tsx frontend/src/components/ChartPanel.test.tsx frontend/src/components/IncomeComposition.tsx frontend/src/components/IncomeComposition.test.tsx
git commit -m "feat: add unified income composition presentation"
```

Expected: focused tests/build pass.

---

### Task 8: Implement the unified business analysis card

**Files:**
- Create: `frontend/src/components/BusinessAnalysisCard.tsx`
- Create: `frontend/src/components/BusinessAnalysisCard.test.tsx`

**Interfaces:**
- Consumes: `storeId`, store-local `today`, `analysisRange`, `analysisSearchParams`, `chartsKey`, additive `ChartsResponse`.
- Produces: one card owning its analysis mode/custom dates and one query that drives KPI, comparison, trend, and composition.

- [ ] **Step 1: Write failing request/range tests**

Using MSW, render `<BusinessAnalysisCard storeId={1} today="2026-07-17" />` and capture requests. Assert the first query is exactly:

```text
/api/charts/1?start=2026-07-01&end=2026-07-17&bucket=day&compare_start=2026-06-01&compare_end=2026-06-17
```

Click `近 6 月` and assert `bucket=month`; click `自定义`, set valid dates, and assert the request has no `compare_start` or `compare_end`. Confirm all KPI, trend, and both composition groups change from the same returned payload.

- [ ] **Step 2: Write failing state/error/accessibility tests**

Cover:

```tsx
expect(screen.getByText("比较区间：2026-06-01 至 2026-06-17")).toBeInTheDocument();
expect(screen.getByText(/按日/)).toBeInTheDocument();
expect(screen.getByText("该范围暂无经营数据")).toBeInTheDocument();
expect(screen.getByRole("button", { name: "重试经营分析" })).toBeInTheDocument();
```

Simulate a successful payload followed by failed invalidation/refetch; assert cached KPI remains visible and `role="alert"` says “刷新失败”. Assert a zero comparison total shows “上期为 0，暂无可比增幅”, never Infinity/NaN.

- [ ] **Step 3: Run the card test and verify it is red**

```powershell
npm test --prefix frontend -- src/components/BusinessAnalysisCard.test.tsx
```

Expected: FAIL because the component does not exist.

- [ ] **Step 4: Implement the query and independent card state**

Use this contract and state:

```ts
interface BusinessAnalysisCardProps { storeId: number; today: string }

const [mode, setMode] = useState<AnalysisRangeMode>("current-month");
const [custom, setCustom] = useState<DateRange>(() => ({ start: `${today.slice(0, 7)}-01`, end: today }));
const resolved = useMemo(() => {
  try { return analysisRange(mode, today, custom); }
  catch { return null; }
}, [mode, today, custom]);
const queryString = resolved ? analysisSearchParams(resolved).toString() : "invalid";
const charts = useQuery({
  queryKey: chartsKey(storeId, queryString),
  enabled: resolved !== null,
  queryFn: () => api<ChartsResponse>(`/charts/${storeId}?${queryString}`),
});
```

Do not call `useStore` or read record filters. The parent resets card state on store change by rendering it with `key={storeId}`.

- [ ] **Step 5: Render one card and exact comparison math**

Select trend rows from `data.range.bucket`:

```ts
const trend = data.range.bucket === "day"
  ? data.daily.map((row) => ({ label: row.date, revenue: chartNumber(row.revenue), revenue_raw: row.revenue }))
  : data.monthly.map((row) => ({ label: row.month, revenue: chartNumber(row.revenue), revenue_raw: row.revenue }));
```

Calculate delta with cents, not floating money:

```ts
const currentCents = amountToCents(data.kpis.total_revenue) ?? 0n;
const previousCents = amountToCents(data.comparison_kpis?.total_revenue ?? "0") ?? 0n;
const deltaCents = currentCents - previousCents;
const deltaTenths = previousCents === 0n ? null : (deltaCents * 1000n) / previousCents;
```

Render current/comparison dates and bucket as text, KPI values, one embedded `ChartPanel`, and one `IncomeComposition` inside the same outer `Card`. For query failure without data show card-local alert/retry; for `isRefetchError` with data keep content and add “刷新失败”.

- [ ] **Step 6: Run focused tests/build and commit**

```powershell
npm test --prefix frontend -- src/components/BusinessAnalysisCard.test.tsx src/components/IncomeComposition.test.tsx src/components/ChartPanel.test.tsx
npm run build --prefix frontend
git add frontend/src/components/BusinessAnalysisCard.tsx frontend/src/components/BusinessAnalysisCard.test.tsx
git commit -m "feat: add unified business analysis card"
```

Expected: focused tests/build pass.

---

### Task 9: Assemble `BusinessRecordsPage`

**Files:**
- Create: `frontend/src/pages/BusinessRecordsPage.tsx`
- Create: `frontend/src/pages/BusinessRecordsPage.test.tsx`
- Modify: `frontend/src/router.tsx`
- Delete: `frontend/src/pages/DatabasePage.tsx`
- Delete: `frontend/src/pages/DatabasePage.test.tsx`

**Interfaces:**
- Consumes: all record/detail/management/analysis components, `databaseKey`, `downloadBusinessRecords`, selected store/user.
- Produces: responsive `/database` page with independent queries/states and preserved admin/user workflows.

- [ ] **Step 1: Port page-level regressions before deleting the old page tests**

Create `BusinessRecordsPage.test.tsx` and port the ordinary-user, admin delete/history/rollback, stale delete conflict, and stale previous-store mutation assertions from `DatabasePage.test.tsx`. Change selectors only to the new table/list/detail controls; do not weaken permission or expected-version assertions.

- [ ] **Step 2: Add failing orchestration tests with captured request URLs**

Assert the initial record request is:

```text
/api/database/1/records?start=2026-07-01&end=2026-07-31&page=1&page_size=15
```

Add exact cases for:

- initial success selects the first returned record;
- record range/page change resets selection to the new page's first record;
- analysis preset changes do not issue a database request;
- record preset changes do not alter the charts query;
- record error leaves analysis visible and analysis error leaves records visible;
- empty records show “暂无可查看记录”, “补记记录”, and usable analysis;
- store change clears old detail immediately, resets page/ranges, closes sheets/dialogs, and ignores delayed old-store responses;
- export uses the record range and failure shows “导出失败，请重试” without changing filters, page, or selection.

- [ ] **Step 3: Run the new page test and verify it is red**

```powershell
npm test --prefix frontend -- src/pages/BusinessRecordsPage.test.tsx
```

Expected: FAIL because `BusinessRecordsPage` does not exist.

- [ ] **Step 4: Implement record state/query and selection invariants**

Use:

```ts
const PAGE_SIZE = 15 as const;
const today = selected ? storeLocalToday(selected) : "1970-01-01";
const [recordMode, setRecordMode] = useState<RecordRangeMode>("current-month");
const [range, setRange] = useState<DateRange>(() => recordRange("current-month", today));
const [page, setPage] = useState(1);
const [selectedRecordId, setSelectedRecordId] = useState<number | null>(null);
const [mobileRecord, setMobileRecord] = useState<RecordSnapshot | null>(null);
const [returnFocusTo, setReturnFocusTo] = useState<HTMLButtonElement | null>(null);
const [managementOpen, setManagementOpen] = useState(false);
const [managementDate, setManagementDate] = useState<string | null>(null);

useEffect(() => {
  if (!selected) return;
  setRecordMode("current-month");
  setRange(recordRange("current-month", storeLocalToday(selected)));
  setPage(1);
  setSelectedRecordId(null);
  setMobileRecord(null);
  setReturnFocusTo(null);
  setManagementOpen(false);
  setManagementDate(null);
}, [selected?.id, today]);

const handleRecordRangeChange = (nextMode: RecordRangeMode, nextRange: DateRange) => {
  setRecordMode(nextMode);
  setRange(nextRange);
  setPage(1);
  setSelectedRecordId(null);
  setMobileRecord(null);
};

const handlePageChange = (nextPage: number) => {
  setPage(nextPage);
  setSelectedRecordId(null);
  setMobileRecord(null);
};
```

Before rendering the query-driven layout, return a page-local `role="status"` message “请先选择门店。” when `selected` is null. The fallback date exists only to initialize hooks and must never issue a request.

Build the query exactly:

```ts
const recordParams = new URLSearchParams({
  start: range.start,
  end: range.end,
  page: String(page),
  page_size: String(PAGE_SIZE),
});
const records = useQuery({
  queryKey: databaseKey(selected.id, recordParams.toString()),
  queryFn: () => api<DatabaseResponse>(`/database/${selected.id}/records?${recordParams.toString()}`),
});
```

On range/page change set selected ID and mobile record to null before changing query inputs. On successful data select `items[0]?.id ?? null`. Derive detail only from the current response and require `record.store_id === selected.id`, preventing a same-ID row from another store from flashing.

- [ ] **Step 5: Implement export mutation and error isolation**

Use:

```ts
const exportMutation = useMutation({
  mutationFn: ({ storeId, requestedRange }: { storeId: number; requestedRange: DateRange }) =>
    downloadBusinessRecords(storeId, requestedRange),
});
const exportError = exportMutation.isError ? friendlyApiError(exportMutation.error, "导出失败，请重试") : "";
```

Pass only the current record range. Do not use analysis dates or page parameters.

- [ ] **Step 6: Implement exact responsive layout and overlays**

Use this structure:

```tsx
<section className="grid w-full gap-4">
  <header><h1 className="text-2xl font-semibold">营业记录</h1></header>
  <RecordFilters
    mode={recordMode}
    range={range}
    today={today}
    exporting={exportMutation.isPending}
    exportError={exportError}
    onChange={handleRecordRangeChange}
    onExport={() => exportMutation.mutate({ storeId: selected.id, requestedRange: range })}
  />
  <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(22rem,24rem)] lg:items-start">
    <div className="min-w-0 overflow-x-hidden">
      <div className="hidden lg:block">
        <RecordTable
          records={records.data?.items ?? []}
          selectedId={selectedRecordId}
          loading={records.isLoading}
          error={records.error}
          onSelect={(record) => setSelectedRecordId(record.id)}
          onRetry={() => void records.refetch()}
        />
      </div>
      <div className="lg:hidden">
        <MobileRecordList
          records={records.data?.items ?? []}
          selectedId={selectedRecordId}
          onSelect={(record, trigger) => {
            setSelectedRecordId(record.id);
            setMobileRecord(record);
            setReturnFocusTo(trigger);
          }}
        />
      </div>
      <RecordPagination
        page={page}
        total={records.data?.total ?? 0}
        pageSize={PAGE_SIZE}
        onPageChange={handlePageChange}
      />
    </div>
    <aside className="grid gap-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
      <div className="hidden lg:block">
        {selectedRecord ? (
          <RecordDetailPanel
            record={selectedRecord}
            canEdit
            canManage={isAdmin}
            onManage={() => {
              setManagementDate(selectedRecord.date);
              setManagementOpen(true);
            }}
          />
        ) : <p>暂无可查看记录</p>}
      </div>
      <BusinessAnalysisCard key={selected.id} storeId={selected.id} today={today} />
    </aside>
  </div>
  {mobileRecord && mobileRecord.store_id === selected.id && (
    <MobileRecordSheet
      open
      record={mobileRecord}
      canEdit
      canManage={isAdmin}
      returnFocusTo={returnFocusTo}
      onOpenChange={(open) => { if (!open) setMobileRecord(null); }}
      onManage={() => {
        setManagementDate(mobileRecord.date);
        setManagementOpen(true);
      }}
    />
  )}
  <RecordManagementDialogs
    storeId={selected.id}
    record={selectedRecord}
    targetDate={managementDate}
    open={managementOpen}
    onOpenChange={setManagementOpen}
    onCompleted={() => setMobileRecord(null)}
  />
</section>
```

Use actual props in the implementation. Open the sheet only from mobile row activation; closing it must not alter range/page/selection/scroll. Both desktop and mobile manage buttons open the same management component.

- [ ] **Step 7: Route `/database` to the new page and remove the old page**

In `router.tsx`, replace `DatabasePage` import/element with `BusinessRecordsPage`. Keep `/charts` temporarily until Task 10 so page migration and route cleanup have separate review gates. Delete old page/test only after every ported regression passes.

- [ ] **Step 8: Run focused/full frontend checks and commit**

```powershell
npm test --prefix frontend -- src/pages/BusinessRecordsPage.test.tsx src/components/RecordManagementDialogs.test.tsx src/components/BusinessAnalysisCard.test.tsx
npm test --prefix frontend
npm run build --prefix frontend
git add frontend/src/pages/BusinessRecordsPage.tsx frontend/src/pages/BusinessRecordsPage.test.tsx frontend/src/pages/DatabasePage.tsx frontend/src/pages/DatabasePage.test.tsx frontend/src/router.tsx
git commit -m "feat: merge records and analytics page"
```

Expected: all frontend unit tests/build pass; `/database` renders the merged page and management regressions remain covered.

---

### Task 10: Remove the obsolete frontend analytics chain

**Files:**
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/navigation/modules.ts`
- Modify: `frontend/src/pages/MorePage.tsx`
- Modify: `frontend/src/layouts/AppShell.tsx`
- Modify: `frontend/src/App.test.tsx`
- Delete: `frontend/src/pages/ChartsPage.tsx`
- Delete: `frontend/src/pages/ChartsPage.test.tsx`

**Interfaces:**
- Consumes: merged `/database` page.
- Produces: one desktop “营业记录” link, unchanged mobile “记录” link, no More analytics link, and not-found behavior for `/charts`.

- [ ] **Step 1: Write failing navigation/route assertions first**

Update `App.test.tsx` to assert:

```ts
expect(within(screen.getByRole("navigation", { name: "主导航" })).getAllByRole("link").map((link) => link.textContent)).toEqual(["首页", "每日记账", "营业记录", "管理中心"]);
expect(screen.queryByRole("link", { name: "历史记录" })).not.toBeInTheDocument();
expect(screen.queryByRole("link", { name: "经营分析" })).not.toBeInTheDocument();
```

Add a memory-router case that enters `/charts` and asserts no `ChartsPage` heading/content is rendered and the router reaches its existing unmatched-route behavior without redirecting to `/database`.

- [ ] **Step 2: Run navigation tests and verify old links fail**

```powershell
npm test --prefix frontend -- src/App.test.tsx
```

Expected: FAIL because desktop and More still expose the old analytics chain.

- [ ] **Step 3: Delete the route, links, icon, page, and page test**

Apply these exact changes:

```ts
const desktopModules = [
  { to: "/", label: "首页", end: true },
  { to: "/ledger", label: "每日记账" },
  { to: "/database", label: "营业记录" },
] as const;
```

Remove `ChartsPage` import and `{ path: "charts", element: <ChartsPage /> }`, remove the More `<Link to="/charts">`, remove `BarChart3` and the `"/charts"` icon entry, then delete `ChartsPage.tsx` and its test. Do not remove backend charts code, `ChartsResponse`, `chartsKey`, or `BusinessAnalysisCard`.

- [ ] **Step 4: Search for obsolete live-chain references**

```powershell
rg -n 'to="/charts"|path: "charts"|ChartsPage|label: "历史记录"|label: "经营分析"' frontend/src
```

Expected: no matches. The visible heading “经营分析” inside `BusinessAnalysisCard` is allowed because the expression above targets route/navigation declarations.

- [ ] **Step 5: Run tests/build and commit**

```powershell
npm test --prefix frontend -- src/App.test.tsx
npm test --prefix frontend
npm run build --prefix frontend
git add frontend/src/router.tsx frontend/src/navigation/modules.ts frontend/src/pages/MorePage.tsx frontend/src/layouts/AppShell.tsx frontend/src/App.test.tsx frontend/src/pages/ChartsPage.tsx frontend/src/pages/ChartsPage.test.tsx
git commit -m "refactor: remove obsolete charts page"
```

Expected: tests/build pass and `/charts` has no frontend route.

---

### Task 11: Complete browser acceptance and full verification

**Files:**
- Modify: `frontend/tests/daily-flow.spec.ts`
- Modify: `frontend/tests/responsive.spec.ts`
- Modify as defects require: owning unit/component files from Tasks 2-10

**Interfaces:**
- Consumes: final merged page and mocked browser API contract including additive charts fields.
- Produces: automated desktop/mobile acceptance evidence and a fully verified implementation branch.

- [ ] **Step 1: Update Playwright API fixtures to the additive contract**

Every `/api/charts/1` mock must include:

```ts
{
  kpis: { total_revenue: "100.00", record_days: 1, open_days: 1, average_revenue: "100.00", primary_categories: [], total_wash_count: null, average_ticket: null },
  range: { start: "2026-07-01", end: "2026-07-17", bucket: "day" },
  comparison_kpis: { start: "2026-06-01", end: "2026-06-17", total_revenue: "80.00", open_days: 1, average_revenue: "80.00" },
  classified_included_total: "100.00",
  daily: [{ date: "2026-07-14", revenue: "100.00" }],
  categories: [{ category_id: 1, category_name: "现金", amount: "100.00" }],
  excluded_categories: [{ category_id: 8, category_name: "优惠券", amount: "5.00" }],
  monthly: [{ month: "2026-07", revenue: "100.00" }],
  weather: [],
  weekday: [],
}
```

Database mocks must honor `page`, `page_size=15`, and descending dates instead of always returning page 1.

- [ ] **Step 2: Rewrite the end-to-end merged workflow**

In `daily-flow.spec.ts`, cover this exact sequence on desktop and 320px:

1. Save a daily record.
2. Navigate through “营业记录”/“记录” to `/database`.
3. Verify selected-day detail and edit action.
4. Change record page/range and verify first-row auto-selection.
5. Change analysis to “近 6 月” and verify record page/range do not change.
6. Verify included/excluded groups, independent expansion, separator notes, and no excluded percent.
7. Trigger export and verify current record dates are sent.
8. Visit `/charts` directly and verify no analytics page/redirect exists.

- [ ] **Step 3: Rewrite responsive acceptance tests**

Desktop assertions:

```ts
await expect(page.getByRole("table")).toBeVisible();
await expect(page.getByRole("complementary")).toBeVisible();
await expect.poll(() => page.getByRole("complementary").evaluate((node) => getComputedStyle(node).position)).toBe("sticky");
```

At 320px assert exact document/body/viewport widths are 320, desktop table/detail are hidden, mobile list has date/status/revenue only, row click opens a bottom dialog, close restores row focus/scroll, safe-area content clears the fixed bottom navigation, and analysis remains vertically reachable below pagination.

- [ ] **Step 4: Run the two acceptance files and fix defects test-first**

```powershell
npm run test:e2e --prefix frontend -- tests/daily-flow.spec.ts tests/responsive.spec.ts
```

Expected: PASS. For each defect found, first add a focused unit/component regression in the owning test file, observe it fail, implement the correction, rerun the focused test, then rerun Playwright. Do not add arbitrary timeouts; wait for API responses or accessible UI state.

- [ ] **Step 5: Run fresh full verification**

```powershell
backend\.venv\Scripts\ruff.exe check backend/app backend/tests
Push-Location backend
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing tests
Pop-Location
npm test --prefix frontend
npm run build --prefix frontend
npm run test:e2e --prefix frontend
git diff --check
```

Expected: every command exits 0; record exact test counts and coverage in the handoff.

- [ ] **Step 6: Perform visual QA with the in-app browser skill**

Use `browser:control-in-app-browser` on the local app and inspect:

- populated desktop page 1 and page 2;
- desktop empty record range with populated analysis;
- desktop analysis failure with usable records;
- right rail content taller than the viewport and independently scrollable;
- 320px list, bottom sheet, focus restoration, and bottom-navigation clearance;
- both composition groups expanded with long category names.

Capture screenshots for defects, verify no horizontal clipping, and add automated regressions before fixes.

- [ ] **Step 7: Commit acceptance updates**

```powershell
git add frontend/tests/daily-flow.spec.ts frontend/tests/responsive.spec.ts frontend/src backend
git commit -m "test: cover merged business records experience"
```

- [ ] **Step 8: Invoke completion skills**

Use `superpowers:verification-before-completion` with fresh command output, then `superpowers:requesting-code-review`. After review findings are resolved and verification is fresh, use `superpowers:finishing-a-development-branch` to offer merge/PR/cleanup choices.
