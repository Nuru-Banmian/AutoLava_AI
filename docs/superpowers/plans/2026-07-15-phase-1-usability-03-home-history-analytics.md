# Phase 1 Usability 03: Home, History, and Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved three-card home, calendar-first history page, and focused revenue analytics without inventing historical category data.

**Architecture:** Replace dashboard prose blobs with a structured cached response so the frontend can render states and actions safely. Reuse `MonthCalendar` from plan 02 for history. Keep the existing charts endpoint but reduce the UI to reliable KPIs, daily revenue trend, and meaningful composition only.

**Tech Stack:** FastAPI, SQLAlchemy async, React, TypeScript, TanStack Query, Recharts, Pytest, Vitest, Playwright.

## Global Constraints

- Home remains exactly yesterday, today, tomorrow plus immediate ledger action.
- Yesterday contains no AI, weather, categories, wash count, or activity.
- Tomorrow never says 尚未记账 and never predicts revenue.
- History has no search box and no global 补记一天 button.
- Historical total-only records are never fabricated into category composition.

---

### Task 1: Structured Dashboard Card Contract

**Files:**
- Create: `backend/alembic/versions/0005_structured_dashboard_cards.py`
- Modify: `backend/app/models/operations.py`
- Create: `backend/app/schemas/dashboard.py`
- Modify: `backend/app/services/briefing.py`
- Modify: `backend/app/api/routes/dashboard.py`
- Modify: `backend/tests/services/test_briefing.py`
- Modify: `backend/tests/api/test_dashboard.py`

**Interfaces:**
- Produces: `DashboardCardResponse(card_type, state, revenue, weather, weekday, temperature_max, temperature_min, precipitation, hint, generated_at)`

- [ ] **Step 1: Test all yesterday states**

```py
@pytest.mark.parametrize((record_status, expected_state), [
    (None, "missing"), ("营业", "recorded"), ("休息", "rest"), ("天气停业", "weather_closed"),
])
async def test_yesterday_is_deterministic(record_status, expected_state, briefing_service):
    card = await briefing_service.build_yesterday(store_id=1, local_date=date(2026, 7, 15))
    assert card.state == expected_state
    assert card.weather is None
    assert card.hint is None
```

Add two cache-boundary assertions: dashboard GET never calls the weather provider, and changing yesterday's ledger record regenerates only the `yesterday` card.

- [ ] **Step 2: Run and verify failure**

Run: `pytest backend/tests/services/test_briefing.py backend/tests/api/test_dashboard.py -q`
Expected: FAIL because dashboard responses contain only prose `content`.

- [ ] **Step 3: Add the response schema**

```py
class DashboardCardResponse(BaseModel):
    card_type: Literal["yesterday", "today", "tomorrow"]
    state: Literal["missing", "recorded", "rest", "weather_closed", "forecast", "unavailable"]
    revenue: Decimal | None = None
    weather: str | None = None
    weekday: str | None = None
    temperature_max: Decimal | None = None
    temperature_min: Decimal | None = None
    precipitation: Decimal | None = None
    hint: str | None = None
    generated_at: datetime
```

Persist this response in a JSON column so GET remains cache-only:

```py
def upgrade() -> None:
    op.add_column("daily_briefings", sa.Column("payload", sa.JSON(), nullable=True))

def downgrade() -> None:
    op.drop_column("daily_briefings", "payload")
```

Keep the existing `content` column during this compatible migration. New refreshes write both a short human-readable content fallback and the structured payload; GET falls back to `state="unavailable"` for old rows until refreshed.

- [ ] **Step 4: Build approved deterministic payloads**

Yesterday returns only state and revenue. Today returns weather plus record state/revenue. Tomorrow returns weather, weekday, temperatures, and precipitation; `hint` remains null until the later memory source exists. Keep persistence/cache reads and the 04:00 scheduler.

- [ ] **Step 5: Localize refresh limiting**

```py
raise HTTPException(429, "请等待五分钟后再刷新")
```

- [ ] **Step 6: Run dashboard tests**

Run: `pytest backend/tests/services/test_briefing.py backend/tests/api/test_dashboard.py backend/tests/services/test_scheduler.py -q`
Expected: PASS for card states, cached GET, 04:00 schedule, and limiter.

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/0005_structured_dashboard_cards.py backend/app/models/operations.py backend/app/schemas/dashboard.py backend/app/services/briefing.py backend/app/api/routes/dashboard.py backend/tests/services/test_briefing.py backend/tests/api/test_dashboard.py
git commit -m "feat: expose structured dashboard cards"
```

### Task 2: Approved Home UI

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/components/BriefingCards.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`
- Modify: `frontend/src/pages/HomePage.test.tsx`

**Interfaces:**
- Consumes: structured `DashboardCardResponse[]`
- Produces: `/ledger?date=YYYY-MM-DD` links for immediate and yesterday backfill actions.

- [ ] **Step 1: Test missing-yesterday and tomorrow copy**

```tsx
expect(screen.getByText("昨日尚未记录")).toBeInTheDocument();
expect(screen.getByRole("link", { name: "补记昨日" })).toHaveAttribute("href", "/ledger?date=2026-07-14");
expect(screen.queryByText(/明日.*尚未记账/)).not.toBeInTheDocument();
```

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/pages/HomePage.test.tsx`
Expected: FAIL because cards render prose strings.

- [ ] **Step 3: Add exact frontend type**

```ts
export interface BriefingCard {
  card_type: "yesterday" | "today" | "tomorrow";
  state: "missing" | "recorded" | "rest" | "weather_closed" | "forecast" | "unavailable";
  revenue: string | null;
  weather: string | null;
  weekday: string | null;
  temperature_max: string | null;
  temperature_min: string | null;
  precipitation: string | null;
  hint: string | null;
  generated_at: string;
}
```

- [ ] **Step 4: Render three fixed cards and CTA**

Implement explicit `YesterdayCard`, `TodayCard`, and `TomorrowCard` branches. Never map arbitrary card types into generic KPI tiles. Place `立即记账` below all three cards and keep refresh secondary.

- [ ] **Step 5: Run tests and build**

Run: `npm test -- src/pages/HomePage.test.tsx && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/components/BriefingCards.tsx frontend/src/pages/HomePage.tsx frontend/src/pages/HomePage.test.tsx
git commit -m "feat: render approved home briefing cards"
```

### Task 3: Calendar-First History Page

**Files:**
- Create: `frontend/src/components/RecordDetail.tsx`
- Modify: `frontend/src/pages/DatabasePage.tsx`
- Modify: `frontend/src/pages/DatabasePage.test.tsx`
- Remove after references migrate: `frontend/src/components/RecordTable.tsx`

**Interfaces:**
- Consumes: `MonthCalendar`, `ledgerRecordKey`, `/database/{store}/records?start&end`
- Produces: selected-date detail and edit action.

- [ ] **Step 1: Test calendar-only discovery**

```tsx
expect(screen.getByRole("button", { name: "2026年7月14日，已有记录" })).toBeInTheDocument();
expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
expect(screen.queryByRole("button", { name: "补记一天" })).not.toBeInTheDocument();
```

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/pages/DatabasePage.test.tsx`
Expected: FAIL because the current page is filter/table based.

- [ ] **Step 3: Query one calendar month**

```ts
const [month, setMonth] = useState(today.slice(0, 7));
const start = `${month}-01`;
const end = format(endOfMonth(parseISO(start)), "yyyy-MM-dd");
const records = useQuery({
  queryKey: databaseKey(selected.id, `${start}:${end}`),
  queryFn: () => api<DatabaseResponse>(`/database/${selected.id}/records?start=${start}&end=${end}&page=1&page_size=31`),
});
```

- [ ] **Step 4: Render record or missing state**

```tsx
const selectedRecord = records.data?.items.find((record) => record.date === selectedDate);
{selectedRecord ? <RecordDetail record={selectedRecord} canDelete={user?.role === "admin"} /> :
  <Card><CardContent><p>{formatDate(selectedDate)}尚未记录</p><Link to={`/ledger?date=${selectedDate}`}>补记这一天</Link></CardContent></Card>}
```

Above the calendar, derive the approved compact summaries from the month response: `sum_daily_revenue`, count of recorded days, and average over `is_open == "营业"` records. These summaries must not move the calendar below the first phone viewport.

- [ ] **Step 5: Preserve admin-only audit actions**

Move audit/delete/rollback behind a secondary admin detail action. Ordinary users retain `修改这天记录` only.

- [ ] **Step 6: Run tests and build**

Run: `npm test -- src/pages/DatabasePage.test.tsx && npm run build`
Expected: PASS; no search, no table overflow, dots and missing state work.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/RecordDetail.tsx frontend/src/pages/DatabasePage.tsx frontend/src/pages/DatabasePage.test.tsx frontend/src/components/RecordTable.tsx
git commit -m "feat: replace record table with calendar history"
```

### Task 4: Focused Analytics Contract and UI

**Files:**
- Modify: `backend/app/services/analytics.py`
- Modify: `backend/tests/services/test_analytics.py`
- Modify: `frontend/src/pages/ChartsPage.tsx`
- Modify: `frontend/src/components/ChartPanel.tsx`
- Modify: `frontend/src/components/ChartPanel.test.tsx`
- Modify: `frontend/src/pages/ChartsPage.test.tsx`

**Interfaces:**
- Preserves: `ChartsResponse.daily` and `ChartsResponse.categories`
- Produces: reliable average revenue derived from total revenue / open days.

- [ ] **Step 1: Test total-only history is excluded from composition**

```py
async def test_total_only_records_affect_trend_not_composition(analytics_service, legacy_record):
    result = await analytics_service.report(store_id=1, start=date(2026, 7, 1), end=date(2026, 7, 31), category_ids=[])
    assert result.kpis.total_revenue == Decimal("100.00")
    assert result.daily[0].revenue == Decimal("100.00")
    assert result.categories == []
```

- [ ] **Step 2: Run focused backend tests**

Run: `pytest backend/tests/services/test_analytics.py backend/tests/api/test_charts.py -q`
Expected: PASS or expose any current fabricated category behavior before UI work.

- [ ] **Step 3: Test the approved controls**

```tsx
expect(screen.getByRole("button", { name: "最近 7 天" })).toBeInTheDocument();
expect(screen.getByRole("button", { name: "本月" })).toHaveAttribute("aria-pressed", "true");
expect(screen.getByText("营业额趋势")).toBeInTheDocument();
```

- [ ] **Step 4: Simplify ChartsPage**

Remove weather, weekday, monthly, wash-count, and average-ticket panels from this page. Render 最近 7 天、本月 and 自定义 date controls, three KPI cards, a daily line chart, and a horizontal composition bar/list. Hide composition when `data.categories.length <= 1`.

```tsx
{data.categories.length > 1 && <IncomeComposition items={data.categories} total={data.kpis.total_revenue} />}
```

- [ ] **Step 5: Use theme tokens in charts**

Replace hard-coded color arrays with CSS variables read by Recharts, starting with `var(--primary)` and theme series tokens defined in `index.css`.

- [ ] **Step 6: Run analytics checks**

Run: `pytest backend/tests/services/test_analytics.py backend/tests/api/test_charts.py -q && npm test -- src/pages/ChartsPage.test.tsx src/components/ChartPanel.test.tsx && npm run build`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/analytics.py backend/tests/services/test_analytics.py frontend/src/pages/ChartsPage.tsx frontend/src/components/ChartPanel.tsx frontend/src/components/ChartPanel.test.tsx frontend/src/pages/ChartsPage.test.tsx
git commit -m "feat: focus analytics on revenue trend and composition"
```

### Task 5: Cross-Page Browser Acceptance

**Files:**
- Create: `frontend/tests/daily-flow.spec.ts`
- Modify: `frontend/tests/responsive.spec.ts`

**Interfaces:**
- Consumes: plans 01-03 completed application.

- [ ] **Step 1: Add the daily workflow**

```ts
test("home to ledger to history to analytics", async ({ page }) => {
  await loginAs(page, "admin");
  await page.getByRole("link", { name: "立即记账" }).click();
  await page.getByLabel("现金").fill("100");
  await page.getByRole("button", { name: "保存今日记录" }).click();
  await expect(page.getByRole("status")).toContainText("保存成功");
  await page.getByRole("link", { name: "记录" }).click();
  await expect(page.getByRole("button", { name: /已有记录/ })).toBeVisible();
});
```

- [ ] **Step 2: Run desktop and 320px flows**

Run: `npm run test:e2e -- daily-flow.spec.ts responsive.spec.ts`
Expected: PASS without horizontal overflow or bottom-bar overlap.

- [ ] **Step 3: Run full backend/frontend gates**

Run: `pytest backend/tests -q && npm test && npm run build && npm run test:e2e`
Expected: all checks PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/daily-flow.spec.ts frontend/tests/responsive.spec.ts
git commit -m "test: cover approved daily business flow"
```
