import { expect, test, type Locator, type Page } from "@playwright/test";
import type { LedgerBody, RecordSnapshot } from "../src/api/types";
import { weatherOptions } from "../src/test/weather-options";

interface RangeRequest {
  storeId: number;
  start: string;
  end: string;
}

const stores = [
  { id: 1, name: "Kiritimati 门店", timezone: "Pacific/Kiritimati" },
  { id: 2, name: "Adak 门店", timezone: "America/Adak" },
];

async function wheelToControl(page: Page, control: Locator) {
  const viewport = page.viewportSize()!;
  await page.mouse.move(viewport.width * 0.75, viewport.height * 0.5);
  for (let attempt = 0; attempt < 8; attempt += 1) {
    // Native wheel events return before scrolling finishes. Read stable geometry
    // before choosing the next movement or declaring the control reachable.
    let previousY: number | undefined;
    let stableReadings = 0;
    await expect.poll(async () => {
      const y = (await control.boundingBox())!.y;
      stableReadings = y === previousY ? stableReadings + 1 : 0;
      previousY = y;
      return stableReadings;
    }).toBeGreaterThanOrEqual(2);
    const box = (await control.boundingBox())!;
    const navigation = await page.getByRole("navigation", { name: "移动导航", includeHidden: true }).boundingBox();
    const bottom = navigation?.y ?? viewport.height;
    if (box.y >= 8 && box.y + box.height <= bottom - 8) return;
    await page.mouse.wheel(0, box.y + box.height / 2 - bottom / 2);
    await expect.poll(async () => (await control.boundingBox())!.y).not.toBe(box.y);
  }
  await expect(control).toBeInViewport({ ratio: 1 });
}

test("320px: calendar cells use income shading and expose amounts through exact readings", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 320, height: 844 });
  await mockEditableBusinessRecords(page);
  await page.route("**/api/charts/1?**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    kpis: { total_revenue: 999900000, record_days: 1, open_days: 1, average_revenue: 999900000, primary_categories: [], total_wash_count: null, average_ticket: null },
    range: { start: "2026-06-01", end: "2026-06-30", bucket: "day" }, comparison_kpis: null,
    income_summary: { daily_ledger_revenue: 999900000, confirmed_settlement_income: 0, total_income: 999900000, includes_settlement_income: false }, classified_included_total: 0,
    daily: [{ date: "2026-06-02", revenue: 999900000, is_open: "营业" }], categories: [], excluded_categories: [], monthly: [], weather: [], weekday: [],
  }) }));
  await page.goto("/database");
  await page.getByLabel("月份", { exact: true }).fill("2026-06");
  await page.getByRole("button", { name: "经营分析", exact: true }).click();
  const date = page.getByRole("button", { name: "2026-06-02 营业 €999.900.000", exact: true });
  await wheelToControl(page, date);
  await expect(date).toHaveText("2营业");
  const originalColor = await date.evaluate((element) => getComputedStyle(element).backgroundColor);
  await page.evaluate(() => document.documentElement.style.setProperty("--primary", "oklch(0.5 0.15 255)"));
  await expect.poll(() => date.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(originalColor);
  await expect(date).toHaveCSS("background-color", /\/ 0.2\)/);
  await expect(page.getByRole("button", { name: "2026-06-01 未录入 —", exact: true })).toHaveCSS("background-color", /\/ 0\)/);
  await page.evaluate(() => document.documentElement.style.removeProperty("--primary"));
  await expect(date).toHaveCSS("background-color", originalColor);
  await expect(date).toHaveAttribute("title", "2026-06-02 营业 €999.900.000");
  await expect(page.getByLabel("日历读数日期", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("status", { name: "日历读数" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^查看 .* 每日台账$/ })).toHaveCount(0);
});

test("390px: daily ledger curves keep gaps, expose keyboard readings and open missing calendar dates on the right page", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 390, height: 844 });
  await mockEditableBusinessRecords(page);
  await page.route("**/api/charts/1?**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    kpis: { total_revenue: 925, record_days: 4, open_days: 3, average_revenue: 75, primary_categories: [], total_wash_count: null, average_ticket: null },
    range: { start: "2026-06-01", end: "2026-06-30", bucket: "day" }, comparison_kpis: null,
    income_summary: { daily_ledger_revenue: 225, confirmed_settlement_income: 700, total_income: 925, includes_settlement_income: true }, classified_included_total: 700,
    daily: [{ date: "2026-06-11", revenue: 0, is_open: "营业" }, { date: "2026-06-12", revenue: 75, is_open: "提前休息" }, { date: "2026-06-13", revenue: 0, is_open: "休息" }, { date: "2026-06-15", revenue: 150, is_open: "营业" }],
    comparison_daily: [{ date: "2026-05-01", revenue: 150, is_open: "营业" }],
    period_coverage: { start: "2026-06-01", end: "2026-06-30", record_days: 4, interval_days: 30 },
    comparison_coverage: { start: "2026-05-01", end: "2026-05-30", record_days: 1, interval_days: 30 },
    ledger_comparison: { current_revenue: 225, previous_revenue: 150, change_percent: 50, status: "comparable", short_previous_month: false },
    categories: [{ category_id: null, category_name: "公司结算", amount: 700 }], excluded_categories: [], monthly: [], weather: [], weekday: [],
  }) }));
  await page.goto("/database");
  await page.getByLabel("月份", { exact: true }).fill("2026-06");
  await page.getByRole("button", { name: "经营分析", exact: true }).click();
  await expect(page.getByText("本期已记录 4 / 30 天；上期已记录 1 / 30 天", { exact: true })).toBeVisible();
  await expect(page.getByText("每日台账营业额较上期 +50.0%", { exact: true })).toBeVisible();
  const trend = page.getByRole("region", { name: "每日台账营业额趋势" });
  await expect.poll(async () => ((await trend.locator("path.recharts-line-curve").first().getAttribute("d"))?.match(/M/g) ?? []).length).toBe(2);
  const reading = page.getByLabel("趋势读数日期", { exact: true });
  await reading.selectOption("2026-06-14");
  await expect(page.getByRole("status", { name: "趋势读数" })).toContainText("2026-06-14：未录入，—");
  await reading.focus();
  await reading.press("ArrowUp");
  await expect(page.getByRole("status", { name: "趋势读数" })).toContainText("2026-06-13：休息，€0");
  const missingDate = page.getByRole("button", { name: "2026-06-01 未录入 —", exact: true });
  await wheelToControl(page, missingDate);
  const box = (await missingDate.boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  const detail = page.getByRole("region", { name: "2026-06-01 营业记录详情" });
  await expect(detail).toContainText("未录入");
  await expect(detail.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-06-01");
  await detail.getByRole("button", { name: "返回记录" }).click();
  await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "2026年6月1日 星期一，未录入，—", exact: true })).toBeFocused();
});

for (const width of [320, 390, 768, 1024, 1280]) {
  test(`${width}px: switches between records and a complete analysis workspace without losing the historical page`, async ({ page }) => {
    await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
    await page.setViewportSize({ width, height: 844 });
    await mockEditableBusinessRecords(page);
    await page.goto("/database");

    const recordsView = page.getByRole("button", { name: "记录", exact: true });
    const analysisView = page.getByRole("button", { name: "经营分析", exact: true });
    await expect(recordsView).toHaveAttribute("aria-pressed", "true");
    await expect(analysisView).toHaveAttribute("aria-pressed", "false");
    for (const entry of [recordsView, analysisView]) {
      expect((await entry.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      await expect(entry.locator("svg")).toBeVisible();
    }
    await expect(page.getByText("营业额趋势", { exact: true })).not.toBeVisible();
    const filters = page.getByRole("region", { name: "记录筛选" });
    await filters.getByLabel("月份", { exact: true }).fill("2026-06");
    await page.getByRole("navigation", { name: "记录分页" }).getByRole("button", { name: "下一页" }).click();
    await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
    const selectedEntry = recordEntry(page, width, "2026年6月15日 星期一，营业，€150");
    await selectedEntry.click();
    if (width < 1024) {
      await page.getByRole("button", { name: "返回记录", exact: true }).click();
      await expect(selectedEntry).toBeFocused();
    }
    await page.evaluate(() => window.scrollTo({ top: 60 }));
    await analysisView.focus();
    const recordScroll = await page.evaluate(() => window.scrollY);
    if (width < 1024) expect(recordScroll).toBeGreaterThan(0);

    await analysisView.press("Enter");
    await expect(analysisView).toHaveAttribute("aria-pressed", "true");
    await expect(recordsView).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByText("营业额趋势", { exact: true })).toBeVisible();
    await expect(page.getByText("当前区间：2026-06-01 至 2026-06-30（按日）", { exact: true })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "记录分页" })).not.toBeVisible();
    await page.screenshot({ path: `output/playwright/issue225-${width}-analysis.png`, animations: "disabled" });

    await recordsView.click();
    await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
    await expect(filters.getByLabel("月份", { exact: true })).toHaveValue("2026-06");
    await expect(selectedEntry).toHaveAttribute(width < 1024 ? "aria-pressed" : "aria-selected", "true");
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(recordScroll);
    await expect(page.getByText("营业额趋势", { exact: true })).not.toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: `output/playwright/issue225-${width}-records.png`, animations: "disabled" });
  });
}

for (const width of [320, 390, 768, 1024, 1280]) {
  test(`${width}px: native wheel reaches record pagination and lower analysis controls`, async ({ page }) => {
    await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
    await page.setViewportSize({ width, height: 844 });
    await mockEditableBusinessRecords(page);
    await page.route("**/api/charts/1?**", (route) => {
      const params = new URL(route.request().url()).searchParams;
      const categories = Array.from({ length: 7 }, (_, index) => ({ category_id: index + 1, category_name: `收入分类 ${index + 1}`, amount: 100 }));
      const excluded = Array.from({ length: 7 }, (_, index) => ({ category_id: index + 11, category_name: `其他数据 ${index + 1}`, amount: 10 }));
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        kpis: { total_revenue: 700, record_days: 7, open_days: 7, average_revenue: 100, primary_categories: [], total_wash_count: null, average_ticket: null },
        range: { start: params.get("start"), end: params.get("end"), bucket: params.get("bucket") },
        comparison_kpis: null,
        income_summary: { daily_ledger_revenue: 700, confirmed_settlement_income: 0, total_income: 700, includes_settlement_income: false },
        classified_included_total: 700,
        daily: [{ date: "2026-07-17", revenue: 700 }], categories, excluded_categories: excluded, monthly: [], weather: [], weekday: [],
      }) });
    });
    await page.goto("/database");
    const firstEntry = recordEntry(page, width, "2026年7月18日 星期六，未录入，—");
    await expect(firstEntry).toBeVisible();
    const firstBox = (await firstEntry.boundingBox())!;
    await page.mouse.move(firstBox.x + firstBox.width / 2, firstBox.y + firstBox.height / 2);
    await page.mouse.wheel(0, 2500);
    const pagination = page.getByRole("navigation", { name: "记录分页" });
    await wheelToControl(page, pagination);
    await expect(pagination).toBeInViewport({ ratio: 1 });
    const next = pagination.getByRole("button", { name: "下一页" });
    const nextBox = (await next.boundingBox())!;
    await page.mouse.click(nextBox.x + nextBox.width / 2, nextBox.y + nextBox.height / 2);
    await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();

    await page.mouse.wheel(0, -2500);
    const analysis = page.getByRole("button", { name: "经营分析", exact: true });
    await expect(analysis).toBeInViewport({ ratio: 1 });
    const analysisBox = (await analysis.boundingBox())!;
    await page.mouse.click(analysisBox.x + analysisBox.width / 2, analysisBox.y + analysisBox.height / 2);
    await expect(page.getByRole("region", { name: "收入构成", exact: true })).toBeVisible();
    await page.mouse.move(width * 0.7, 500);
    await page.mouse.wheel(0, 2500);
    const expandOther = page.getByRole("button", { name: "展开其他数据（还有 2 项）", exact: true });
    await wheelToControl(page, expandOther);
    await expect(expandOther).toBeInViewport({ ratio: 1 });
    const expandBox = (await expandOther.boundingBox())!;
    await page.mouse.click(expandBox.x + expandBox.width / 2, expandBox.y + expandBox.height / 2);
    await page.mouse.wheel(0, 1000);
    await wheelToControl(page, page.getByText("其他数据 7", { exact: true }));
    await expect(page.getByText("其他数据 7", { exact: true })).toBeInViewport({ ratio: 1 });
  });
}

async function mockBusinessRecords(page: Page, requests: {
  records: RangeRequest[];
  charts: RangeRequest[];
  pagedRecords?: Array<RangeRequest & { page: number }>;
}) {
  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (value: unknown) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(value),
    });

    if (url.pathname === "/api/auth/me") {
      return json({ id: 1, username: "operator", role: "user", is_owner: false });
    }
    if (url.pathname === "/api/stores/accessible") return json(stores);

    const recordMatch = url.pathname.match(/^\/api\/database\/(\d+)\/records$/);
    if (recordMatch) {
      const range = {
        storeId: Number(recordMatch[1]),
        start: url.searchParams.get("start") ?? "",
        end: url.searchParams.get("end") ?? "",
      };
      const pageNumber = Number(url.searchParams.get("page"));
      requests.records.push(range);
      requests.pagedRecords?.push({ ...range, page: pageNumber });
      const total = range.start === "2025-01-01" && range.end === "2025-12-31" ? 201 : 0;
      return json({ items: [], categories: [], sum_daily_revenue: 0, total, page: pageNumber, page_size: 200 });
    }

    const chartMatch = url.pathname.match(/^\/api\/charts\/(\d+)$/);
    if (chartMatch) {
      const range = {
        storeId: Number(chartMatch[1]),
        start: url.searchParams.get("start") ?? "",
        end: url.searchParams.get("end") ?? "",
      };
      requests.charts.push(range);
      return json({
        kpis: { total_revenue: 0, record_days: 0, open_days: 0, average_revenue: 0, primary_categories: [], total_wash_count: null, average_ticket: null },
        range: { start: range.start, end: range.end, bucket: url.searchParams.get("bucket") ?? "day" },
        comparison_kpis: null,
        income_summary: { daily_ledger_revenue: 0, confirmed_settlement_income: 0, total_income: 0, includes_settlement_income: false },
        classified_included_total: 0,
        daily: [], categories: [], excluded_categories: [], monthly: [], weather: [], weekday: [],
      });
    }

    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: url.pathname }) });
  });
}

async function expectLatestSynchronizedRange(
  requests: { records: RangeRequest[]; charts: RangeRequest[] },
  expected: RangeRequest,
) {
  await expect.poll(() => requests.records.at(-1)).toEqual(expected);
  await expect.poll(() => requests.charts.at(-1)).toEqual(expected);
}

function editableRecord(storeId: number, date: string, amount: number, status: RecordSnapshot["is_open"] = "营业"): RecordSnapshot {
  const id = storeId * 100 + Number(date.slice(-2));
  return {
    id, store_id: storeId, date, identity: `fixture-${storeId}-${date}`, revision: 1, config_revision: 7,
    daily_revenue: amount, income_mode: "legacy_total", is_open: status, items: [], wash_count: status === "休息" ? 0 : 3,
    activity: date === "2026-06-15" ? "可控测试事件" : null, weather: "晴", weather_auto: null, weather_code: 0,
    weather_legacy: false, weather_edited: false, temperature_max: null, temperature_min: null, precipitation: null,
    scanned: false, created_by: 1, updated_by: 1, created_at: `${date}T08:00:00Z`, updated_at: `${date}T08:00:00Z`,
    bookkeeping_events: [{ id, actor_id: 1, actor_name: "测试操作员", action: "created", occurred_at: `${date}T08:00:00Z` }],
  };
}

async function mockEditableBusinessRecords(page: Page, additionalRecords: RecordSnapshot[] = []) {
  const requests = { records: [] as RangeRequest[], charts: [] as RangeRequest[] };
  await mockBusinessRecords(page, requests);
  const records = new Map<string, RecordSnapshot>([
    ["1:2026-06-15", editableRecord(1, "2026-06-15", 150)],
    ["1:2026-06-13", editableRecord(1, "2026-06-13", 0, "休息")],
    ["1:2026-06-12", editableRecord(1, "2026-06-12", 75, "提前休息")],
    ["1:2026-06-11", editableRecord(1, "2026-06-11", 0)],
    ["2:2026-07-17", editableRecord(2, "2026-07-17", 917)],
  ]);
  for (const record of additionalRecords) records.set(`${record.store_id}:${record.date}`, record);
  const contractErrors: string[] = [];
  await page.route("**/api/auth/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: 1, username: "fixture-admin", role: "admin", is_owner: false }) }));
  await page.route(/\/api\/(database\/\d+\/(records|export\.xlsx)|ledger\/|income-config\/|weather\/)/, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
    const databaseMatch = path.match(/^\/api\/database\/(\d+)\/records$/);
    if (databaseMatch) {
      const storeId = Number(databaseMatch[1]);
      const start = url.searchParams.get("start") ?? "";
      const end = url.searchParams.get("end") ?? "";
      const pageNumber = Number(url.searchParams.get("page"));
      const pageSize = Number(url.searchParams.get("page_size"));
      requests.records.push({ storeId, start, end });
      const items = [...records.values()].filter((record) => record.store_id === storeId && record.date >= start && record.date <= end);
      return json({ items: items.slice((pageNumber - 1) * pageSize, pageNumber * pageSize), categories: [], sum_daily_revenue: items.reduce((sum, item) => sum + item.daily_revenue, 0), total: items.length, page: pageNumber, page_size: pageSize });
    }
    if (/^\/api\/database\/\d+\/export\.xlsx$/.test(path)) return route.fulfill({ status: 200, contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", body: "controlled export fixture" });
    if (path === "/api/ledger/weather-options") return json(weatherOptions);
    if (/^\/api\/weather\/\d+\/\d{4}-\d{2}-\d{2}$/.test(path)) return json({ weather: null, weather_code: null, temperature_max: null, temperature_min: null, precipitation: null });
    const configMatch = path.match(/^\/api\/income-config\/(\d+)\/current$/);
    if (configMatch) return json({ store_id: Number(configMatch[1]), revision: 7, enabled: false, formula: "", items: [] });
    const ledgerMatch = path.match(/^\/api\/ledger\/(\d+)\/(\d{4}-\d{2}-\d{2})$/);
    if (ledgerMatch) {
      const storeId = Number(ledgerMatch[1]);
      const date = ledgerMatch[2];
      const key = `${storeId}:${date}`;
      const existing = records.get(key);
      if (request.method() === "GET") return existing ? json(existing) : json({ detail: "Record not found" }, 404);
      const body = request.postDataJSON() as LedgerBody;
      if (body.expected_identity !== (existing?.identity ?? null) || body.expected_revision !== (existing?.revision ?? null)) {
        contractErrors.push(`invalid record revision for ${key}`);
        return json({ detail: "fixture rejected stale revision" }, 409);
      }
      if (request.method() === "DELETE") {
        records.delete(key);
        return route.fulfill({ status: 204 });
      }
      if (request.method() === "PUT" && body.expected_config_revision === 7 && body.items.length === 0 && Number.isSafeInteger(body.daily_revenue)) {
        const saved = { ...editableRecord(storeId, date, body.is_open === "休息" ? 0 : body.daily_revenue!, body.is_open), revision: (existing?.revision ?? 0) + 1, activity: body.activity ?? null, wash_count: body.wash_count ?? null };
        records.set(key, saved);
        return json({ id: saved.id, identity: saved.identity, revision: saved.revision, config_revision: 7, date, daily_revenue: saved.daily_revenue }, existing ? 200 : 201);
      }
    }
    contractErrors.push(`unhandled ${request.method()} ${path}`);
    return json({ detail: "Unexpected fixture request" }, 500);
  });
  return { requests, contractErrors };
}

for (const width of [320, 390, 768]) {
  test(`${width}px: current-page detail returns to the same historical row, focus, and position`, async ({ page }) => {
    await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
    await page.setViewportSize({ width, height: 844 });
    const fixture = await mockEditableBusinessRecords(page);
    await page.goto("/database");
    const filters = page.getByRole("region", { name: "记录筛选" });
    await filters.getByLabel("月份", { exact: true }).fill("2026-06");
    await page.getByRole("navigation", { name: "记录分页" }).getByRole("button", { name: "下一页" }).click();
    const trigger = page.getByRole("button", { name: "2026年6月15日 星期一，营业，€150", exact: true });
    await expect(trigger).toBeVisible();
    await page.evaluate(() => window.scrollTo({ top: 180 }));
    const scrollY = await page.evaluate(() => window.scrollY);
    expect(scrollY).toBeGreaterThan(0);
    await trigger.click();

    const detail = page.getByRole("region", { name: "2026-06-15 营业记录详情" });
    await expect(detail).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(filters).not.toBeVisible();
    await expect(page.getByRole("group", { name: "营业记录视图" })).not.toBeVisible();
    await expect(detail).toContainText("可控测试事件");
    await expect(detail).toContainText("记账事件");
    const title = detail.getByRole("heading", { name: "2026年6月15日 星期一", exact: true });
    const back = detail.getByRole("button", { name: "返回记录", exact: true });
    await expect(title).toBeFocused();
    const titleBox = await title.boundingBox();
    const backBox = await back.boundingBox();
    expect(titleBox).not.toBeNull();
    expect(backBox).not.toBeNull();
    expect(backBox!.y).toBeLessThan(titleBox!.y + titleBox!.height);
    expect(backBox!.y + backBox!.height).toBeGreaterThan(titleBox!.y);
    await back.click();
    await expect(detail).not.toBeVisible();
    await expect(filters.getByLabel("月份", { exact: true })).toHaveValue("2026-06");
    await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
    await expect(trigger).toHaveAttribute("aria-pressed", "true");
    await expect(trigger).toBeFocused();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(scrollY);

    await trigger.click();
    await expect(detail).toBeVisible();
    await page.goBack();
    await expect(detail).not.toBeVisible();
    await expect(trigger).toBeFocused();
    await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
    expect(fixture.contractErrors).toEqual([]);
  });
}

function recordEntry(page: Page, width: number, name: string) {
  return width < 1024
    ? page.getByRole("button", { name, exact: true })
    : page.getByRole("table").getByRole("row", { name: new RegExp(`^${name.replaceAll("，", " ")}(?: |$)`) });
}

function recordDetail(page: Page, width: number, date: string, title: string) {
  return width < 1024
    ? page.getByRole("region", { name: `${date} 营业记录详情` })
    : page.getByRole("complementary").filter({ has: page.getByRole("heading", { name: title, exact: true }) });
}

for (const width of [390, 1280]) {
  test(`${width}px: analysis loading and retry failure stay independent from usable records`, async ({ page }) => {
    await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
    await page.setViewportSize({ width, height: 844 });
    const fixture = await mockEditableBusinessRecords(page);
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    let attempts = 0;
    let allowSuccess = false;
    await page.route("**/api/charts/1?**", async (route) => {
      attempts += 1;
      if (attempts === 1) await pending;
      if (allowSuccess) return route.fallback();
      return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "controlled chart outage" }) });
    });
    await page.goto("/database");
    const currentDate = recordEntry(page, width, "2026年7月18日 星期六，未录入，—");
    await expect(currentDate).toBeVisible();
    await page.getByRole("button", { name: "经营分析", exact: true }).click();
    await expect(page.getByText("加载经营分析…", { exact: true })).toBeVisible();
    release();
    await expect(page.getByText("经营分析加载失败", { exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("region", { name: "星期经营表现", exact: true })).toHaveCount(0);
    await expect(page.getByRole("region", { name: "天气与营业额对比", exact: true })).toHaveCount(0);
    expect(attempts).toBeGreaterThan(1);
    await page.getByRole("button", { name: "记录", exact: true }).click();
    await expect(currentDate).toBeVisible();
    await expect(page.getByText("加载记录失败，请重试。", { exact: true })).not.toBeVisible();
    const recordsReadCount = fixture.requests.records.length;
    await page.getByRole("button", { name: "经营分析", exact: true }).click();
    allowSuccess = true;
    await page.getByRole("button", { name: "重试经营分析", exact: true }).click();
    await expect(page.getByText("营业额趋势", { exact: true })).toBeVisible();
    await expect(page.getByText("经营分析加载失败", { exact: true })).not.toBeVisible();
    expect(fixture.requests.records.length).toBe(recordsReadCount);
    expect(fixture.contractErrors).toEqual([]);
  });
}

for (const width of [390, 1280]) {
  test(`${width}px: grouped readings survive refresh failures and discard late previous-scope charts`, async ({ page }) => {
    await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
    await page.setViewportSize({ width, height: 844 });
    await mockEditableBusinessRecords(page);
    let failJune = false;
    let holdJuly = false;
    let julyStarted = false;
    let releaseJuly!: () => void;
    const pendingJuly = new Promise<void>((resolve) => { releaseJuly = resolve; });
    let markJulyFinished!: () => void;
    const julyFinished = new Promise<void>((resolve) => { markJulyFinished = resolve; });
    await page.route("**/api/charts/*?**", async (route) => {
      const url = new URL(route.request().url());
      const start = url.searchParams.get("start")!;
      const storeId = Number(url.pathname.split("/").at(-1));
      if (failJune && start === "2026-06-01") return route.fulfill({ status: 503, body: "{}", contentType: "application/json" });
      const delayed = holdJuly && storeId === 1 && start === "2026-07-01";
      if (delayed) { julyStarted = true; await pendingJuly; }
      const amount = storeId === 2 ? 55 : start === "2026-06-01" ? 42 : 999;
      const weather = storeId === 2 ? "多云" : start === "2026-06-01" ? "中雨" : "晴";
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        kpis: { total_revenue: amount, record_days: 1, open_days: 1, average_revenue: amount, primary_categories: [], total_wash_count: null, average_ticket: null },
        range: { start, end: url.searchParams.get("end"), bucket: "day" }, comparison_kpis: null,
        income_summary: { daily_ledger_revenue: amount, confirmed_settlement_income: 0, total_income: amount, includes_settlement_income: false },
        classified_included_total: 0, daily: [], categories: [], excluded_categories: [], monthly: [],
        weekday: [{ weekday: 0, average_revenue: amount, operating_day_count: 1 }],
        weather: [{ weather, average_revenue: amount, operating_day_count: 1 }],
      }) });
      if (delayed) markJulyFinished();
    });
    await page.goto("/database");
    const filters = page.getByRole("region", { name: "记录筛选" });
    await filters.getByLabel("月份", { exact: true }).fill("2026-06");
    await page.getByRole("button", { name: "经营分析", exact: true }).click();
    const juneGroup = page.getByRole("listitem", { name: "中雨：€42，1 天经营日样本", exact: true });
    await expect(juneGroup).toBeVisible();
    await filters.getByLabel("月份", { exact: true }).fill("2026-07");
    await expect(page.getByRole("listitem", { name: "晴：€999，1 天经营日样本", exact: true })).toBeVisible();
    failJune = true;
    await filters.getByLabel("月份", { exact: true }).fill("2026-06");
    await expect(page.getByText("刷新经营分析失败，当前显示上次取得的数据。", { exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(juneGroup).toBeVisible();
    failJune = false;
    await page.getByRole("button", { name: "重试经营分析", exact: true }).click();
    await expect(page.getByText("刷新经营分析失败，当前显示上次取得的数据。", { exact: true })).toHaveCount(0);
    holdJuly = true;
    await filters.getByLabel("月份", { exact: true }).fill("2026-07");
    await expect.poll(() => julyStarted).toBe(true);
    const picker = page.getByTestId(width < 1024 ? "mobile-store-picker" : "desktop-store-picker");
    await picker.getByLabel("门店", { exact: true }).selectOption("2");
    await expect(page.getByRole("listitem", { name: "多云：€55，1 天经营日样本", exact: true })).toBeVisible();
    releaseJuly();
    await julyFinished;
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(page.getByRole("listitem", { name: "晴：€999，1 天经营日样本", exact: true })).toHaveCount(0);
    await expect(page.getByRole("listitem", { name: "多云：€55，1 天经营日样本", exact: true })).toBeVisible();
  });
}

for (const width of [390, 1280]) {
  test(`${width}px: cached record and analysis refresh failures retain facts and recover independently after actual retries`, async ({ page }) => {
    await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
    await page.setViewportSize({ width, height: 844 });
    const fixture = await mockEditableBusinessRecords(page);
    let failJune = false;
    let allowRecords = false;
    let allowCharts = false;
    const attempts = { records: 0, charts: 0 };
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    await page.route(/\/api\/(database\/1\/records|charts\/1)\?/, async (route) => {
      const url = new URL(route.request().url());
      if (!failJune || url.searchParams.get("start") !== "2026-06-01") return route.fallback();
      const kind = url.pathname.includes("/charts/") ? "charts" : "records";
      attempts[kind] += 1;
      if (attempts[kind] === 1) await pending;
      if (kind === "charts" ? allowCharts : allowRecords) return route.fallback();
      return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "controlled refresh outage" }) });
    });
    await page.goto("/database");
    const filters = page.getByRole("region", { name: "记录筛选" });
    await filters.getByLabel("月份", { exact: true }).fill("2026-06");
    await page.getByRole("button", { name: "经营分析", exact: true }).click();
    await expect(page.getByText("当前区间：2026-06-01 至 2026-06-30（按日）", { exact: true })).toBeVisible();
    await filters.getByLabel("月份", { exact: true }).fill("2026-07");
    await expect(page.getByText("当前区间：2026-07-01 至 2026-07-31（按日）", { exact: true })).toBeVisible();
    failJune = true;
    await filters.getByLabel("月份", { exact: true }).fill("2026-06");
    await expect(page.getByText("正在刷新经营分析…", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "记录", exact: true }).click();
    await expect(page.getByText("正在刷新记录…", { exact: true })).toBeVisible();
    await page.getByRole("navigation", { name: "记录分页" }).getByRole("button", { name: "下一页" }).click();
    const saved = recordEntry(page, width, "2026年6月15日 星期一，营业，€150");
    await expect(saved).toBeVisible();
    release();
    await expect(page.getByText("刷新记录失败，当前显示上次取得的数据。", { exact: true })).toBeVisible({ timeout: 15_000 });
    expect(attempts.records).toBeGreaterThan(1);
    await expect(saved).toBeVisible();
    await page.getByRole("button", { name: "经营分析", exact: true }).click();
    await expect(page.getByText("刷新经营分析失败，当前显示上次取得的数据。", { exact: true })).toBeVisible({ timeout: 15_000 });
    expect(attempts.charts).toBeGreaterThan(1);
    await expect(page.getByText("当前区间：2026-06-01 至 2026-06-30（按日）", { exact: true })).toBeVisible();
    allowCharts = true;
    await page.getByRole("button", { name: "重试经营分析", exact: true }).click();
    await expect(page.getByText("刷新经营分析失败，当前显示上次取得的数据。", { exact: true })).not.toBeVisible();
    await page.getByRole("button", { name: "记录", exact: true }).click();
    await expect(page.getByText("刷新记录失败，当前显示上次取得的数据。", { exact: true })).toBeVisible();
    if (width === 1280) await page.screenshot({ path: "output/playwright/issue225-1280-refresh-failure.png", animations: "disabled" });
    allowRecords = true;
    await page.getByRole("button", { name: "重试", exact: true }).click();
    await expect(page.getByText("刷新记录失败，当前显示上次取得的数据。", { exact: true })).not.toBeVisible();
    await expect(saved).toBeVisible();
    await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
    expect(fixture.contractErrors).toEqual([]);
  });
}

test("390px: a valid missing-date link opens its second page and invalid links never invent a detail", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 390, height: 844 });
  await mockEditableBusinessRecords(page);
  await page.goto("/database?date=2026-07-03");
  const detail = page.getByRole("region", { name: "2026-07-03 营业记录详情" });
  await expect(detail).toBeVisible();
  await expect(detail).toContainText("未录入");
  await expect(detail.getByRole("link", { name: /^(修改这天记录|补记这天记录)$/ })).toHaveAttribute("href", "/ledger?date=2026-07-03");
  await detail.getByRole("button", { name: "返回记录", exact: true }).click();
  await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
  await expect(recordEntry(page, 390, "2026年7月3日 星期五，未录入，—")).toBeFocused();
  for (const date of ["2026-07-19", "2026-06-14", "2026-07-32", "not-a-date"]) {
    await page.goto(`/database?date=${date}`);
    await expect(page.getByRole("navigation", { name: "记录分页" })).toBeVisible();
    await expect(page.getByRole("region", { name: /营业记录详情$/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "返回记录", exact: true })).toHaveCount(0);
  }
});

for (const width of [1024, 1280]) {
  test(`${width}px: a date detail link switches to analysis without leaving records visible`, async ({ page }) => {
    await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
    await page.setViewportSize({ width, height: 844 });
    await mockEditableBusinessRecords(page);
    await page.goto("/database?date=2026-07-03");
    const recordsTable = page.locator("table");
    const detailHeading = page.getByRole("main").getByRole("complementary", { includeHidden: true }).getByRole("heading", { name: "2026年7月3日 星期五", exact: true, includeHidden: true });
    const pagination = page.getByRole("navigation", { name: "记录分页", includeHidden: true });
    await expect(recordsTable).toBeVisible();
    await expect(detailHeading).toBeVisible();
    await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();

    const analysis = page.getByRole("button", { name: "经营分析", exact: true });
    await analysis.click();
    await expect(analysis).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("营业额趋势", { exact: true })).toBeVisible();
    await expect(recordsTable).not.toBeVisible();
    await expect(detailHeading).not.toBeVisible();
    await expect(pagination).not.toBeVisible();

    await page.getByRole("button", { name: "记录", exact: true }).click();
    await expect(recordsTable).toBeVisible();
    await expect(detailHeading).toBeVisible();
    await expect(recordEntry(page, width, "2026年7月3日 星期五，未录入，—")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
  });
}

for (const width of [1024, 1280]) {
  for (const entry of ["record row", "date detail link"]) {
    test(`${width}px: ${entry} editing returns to the actual scroll position`, async ({ page }) => {
      await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
      await page.setViewportSize({ width, height: 844 });
      const fixture = await mockEditableBusinessRecords(page, [editableRecord(1, "2026-07-17", 170)]);
      let saved = false;
      let releaseReturnRefresh!: () => void;
      const returnRefresh = new Promise<void>((resolve) => { releaseReturnRefresh = resolve; });
      await page.route("**/api/ledger/1/2026-07-17", async (route) => {
        if (route.request().method() === "PUT") saved = true;
        await route.fallback();
      });
      await page.route("**/api/database/1/records?**", async (route) => {
        if (saved && new URL(route.request().frame().url()).pathname === "/database") await returnRefresh;
        await route.fallback();
      });
      const measureScroll = () => page.evaluate(() => ({
        scrollY: window.scrollY,
        documentHeight: document.documentElement.scrollHeight,
        viewportHeight: window.innerHeight,
        scrollMax: document.documentElement.scrollHeight - window.innerHeight,
      }));
      await page.goto(entry === "date detail link" ? "/database?date=2026-07-17" : "/database");
      const selected = recordEntry(page, width, "2026年7月17日 星期五，营业，€170");
      await expect(selected).toBeVisible();
      if (entry === "record row") await selected.click();
      const detail = recordDetail(page, width, "2026-07-17", "2026年7月17日 星期五");
      await expect(detail).toContainText("€170");
      const headingBox = (await detail.getByRole("heading", { name: "2026年7月17日 星期五", exact: true }).boundingBox())!;
      await page.mouse.move(headingBox.x + headingBox.width / 2, headingBox.y + headingBox.height / 2);
      await page.mouse.wheel(0, 300);
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(300);
      const edit = detail.getByRole("link", { name: "修改这天记录", exact: true });
      await expect(edit).toBeInViewport({ ratio: 1 });
      const recordScroll = await page.evaluate(() => window.scrollY);
      const beforeEdit = await measureScroll();
      const editBox = (await edit.boundingBox())!;
      await page.mouse.click(editBox.x + editBox.width / 2, editBox.y + editBox.height / 2);
      await expect(page).toHaveURL(/ledger\?date=2026-07-17$/);
      await page.getByLabel("当日营业额", { exact: true }).fill("270");
      await page.getByRole("button", { name: "保存修改", exact: true }).click();
      await expect(page).toHaveURL(/\/database(?:\?date=2026-07-17)?$/);
      const refreshing = page.getByText("正在刷新记录…", { exact: true });
      await expect(refreshing).toBeVisible();
      const refreshStatusBox = await refreshing.boundingBox();
      const pendingRefresh = await measureScroll();
      releaseReturnRefresh();
      await expect(refreshing).not.toBeVisible();
      await expect(detail).toContainText("€270");
      await expect(page.getByRole("region", { name: "记录筛选" }).getByLabel("月份", { exact: true })).toHaveValue("2026-07");
      await expect(page.getByText("第 1 / 2 页", { exact: true })).toBeVisible();
      await expect(recordEntry(page, width, "2026年7月17日 星期五，营业，€270")).toHaveAttribute("aria-selected", "true");
      try {
        await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(recordScroll);
      } finally {
        await test.info().attach("records-return-geometry", {
          body: JSON.stringify({ width, entry, beforeEdit, pendingRefresh, refreshStatusBox, settled: await measureScroll() }),
          contentType: "application/json",
        });
      }
      expect(fixture.contractErrors).toEqual([]);
    });
  }
}

for (const width of [390, 1280]) {
  test(`${width}px: late charts cannot replace the newly selected store and month`, async ({ page }) => {
    await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
    await page.setViewportSize({ width, height: 844 });
    await mockEditableBusinessRecords(page);
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    let oldRequests = 0;
    let oldResponses = 0;
    await page.route(/\/api\/charts\/[12]\?/, async (route) => {
      const url = new URL(route.request().url());
      const range = { start: url.searchParams.get("start")!, end: url.searchParams.get("end")!, bucket: "day" };
      const isOldMonth = range.start === "2026-07-01";
      const amount = url.pathname.endsWith("/1") ? 111000 : isOldMonth ? 917 : 615;
      if (isOldMonth) {
        oldRequests += 1;
        await pending;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        kpis: { total_revenue: amount, record_days: 1, open_days: 1, average_revenue: amount, primary_categories: [], total_wash_count: null, average_ticket: null },
        range, comparison_kpis: null,
        income_summary: { daily_ledger_revenue: amount, confirmed_settlement_income: 0, total_income: amount, includes_settlement_income: false },
        classified_included_total: 0, daily: [{ date: range.start, revenue: amount }], categories: [], excluded_categories: [], monthly: [], weather: [], weekday: [],
      }) });
      if (isOldMonth) oldResponses += 1;
    });
    await page.goto("/database?date=2026-07-17");
    if (width < 1024) await expect(page.getByRole("region", { name: "2026-07-17 营业记录详情" })).toBeVisible();
    await page.getByTestId(width < 768 ? "mobile-store-picker" : "desktop-store-picker").getByLabel("门店").selectOption("2");
    await expect(page.getByRole("region", { name: /营业记录详情$/ })).toHaveCount(0);
    await page.getByRole("button", { name: "经营分析", exact: true }).click();
    await expect(page.getByText("加载经营分析…", { exact: true })).toBeVisible();
    await page.getByRole("region", { name: "记录筛选" }).getByLabel("月份", { exact: true }).fill("2026-06");
    await expect(page.getByText("当前区间：2026-06-01 至 2026-06-30（按日）", { exact: true })).toBeVisible();
    await expect(page.getByText("€615", { exact: true }).first()).toBeVisible();
    const heldRequests = oldRequests;
    release();
    await expect.poll(() => oldResponses).toBe(heldRequests);
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(page.getByText("€615", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("€111.000", { exact: true })).not.toBeVisible();
    await expect(page.getByText("€917", { exact: true })).not.toBeVisible();
    await expect(page.getByRole("region", { name: "记录筛选" }).getByLabel("月份", { exact: true })).toHaveValue("2026-06");
    await page.getByRole("button", { name: "记录", exact: true }).click();
    await expect(recordEntry(page, width, "2026年6月30日 星期二，未录入，—")).toBeVisible();
  });
}

for (const width of [320, 390, 768, 1024, 1280]) {
  test(`${width}px: historical editing, missing-date entry, deletion, and export preserve the second page`, async ({ page }) => {
    await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
    await page.setViewportSize({ width, height: width === 768 ? 744 : 844 });
    const fixture = await mockEditableBusinessRecords(page);
    let deleteStarted = false;
    let refreshStarted = false;
    let releaseDelete!: () => void;
    let releaseRefresh!: () => void;
    const pendingDelete = new Promise<void>((resolve) => { releaseDelete = resolve; });
    const pendingRefresh = new Promise<void>((resolve) => { releaseRefresh = resolve; });
    await page.route("**/api/ledger/1/2026-06-14", async (route) => {
      if (route.request().method() === "DELETE") {
        deleteStarted = true;
        await pendingDelete;
      }
      await route.fallback();
    });
    await page.route("**/api/database/1/records?**", async (route) => {
      if (deleteStarted) {
        refreshStarted = true;
        await pendingRefresh;
      }
      await route.fallback();
    });
    await page.goto("/database");
    const filters = page.getByRole("region", { name: "记录筛选" });
    await filters.getByLabel("月份", { exact: true }).fill("2026-06");
    await page.getByRole("navigation", { name: "记录分页" }).getByRole("button", { name: "下一页" }).click();
    await expect(recordEntry(page, width, "2026年6月13日 星期六，休息，€0")).toBeVisible();
    await expect(recordEntry(page, width, "2026年6月12日 星期五，提前休息，€75")).toBeVisible();
    await expect(recordEntry(page, width, "2026年6月11日 星期四，营业，€0")).toBeVisible();
    const original = recordEntry(page, width, "2026年6月15日 星期一，营业，€150");
    let originalListScroll = 0;
    if (width < 1024) {
      await page.mouse.move(width / 2, 400);
      await page.mouse.wheel(0, -2500);
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
      await page.mouse.wheel(0, 180);
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(180);
      await expect(original).toBeInViewport({ ratio: 1 });
      originalListScroll = await page.evaluate(() => window.scrollY);
      const originalBox = (await original.boundingBox())!;
      await page.mouse.click(originalBox.x + originalBox.width / 2, originalBox.y + originalBox.height / 2);
    } else await original.click();
    let detail = recordDetail(page, width, "2026-06-15", "2026年6月15日 星期一");
    await detail.getByRole("link", { name: "修改这天记录" }).click();
    await expect(page).toHaveURL(/ledger\?date=2026-06-15$/);
    await expect(page.getByLabel("当日营业额", { exact: true })).toHaveValue("150");
    await page.getByLabel("当日营业额", { exact: true }).fill("250");
    const editedActivity = width < 1024 ? "修改后的可控测试事件\n".repeat(20) : "修改后的可控测试事件";
    await page.getByLabel("事件", { exact: true }).fill(editedActivity);
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await expect(page).toHaveURL(width < 1024 ? /database\?date=2026-06-15$/ : /database$/);
    await expect(detail).toContainText("€250");
    await expect(detail).toContainText("修改后的可控测试事件");
    if (width < 1024) {
      await expect(page.getByText("正在刷新记录…", { exact: true })).not.toBeVisible();
      await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      expect(await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight)).toBeGreaterThan(originalListScroll);
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
      await expect(detail.getByRole("heading", { name: "2026年6月15日 星期一", exact: true })).toBeInViewport({ ratio: 1 });
      await expect(detail.getByRole("heading", { name: "2026年6月15日 星期一", exact: true })).toBeFocused();
      const back = detail.getByRole("button", { name: "返回记录", exact: true });
      await expect(back).toBeInViewport({ ratio: 1 });
      const backBox = (await back.boundingBox())!;
      await page.mouse.click(backBox.x + backBox.width / 2, backBox.y + backBox.height / 2);
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(originalListScroll);
    }
    await expect(filters.getByLabel("月份", { exact: true })).toHaveValue("2026-06");
    await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
    const updated = recordEntry(page, width, "2026年6月15日 星期一，营业，€250");
    await expect(updated).toHaveAttribute(width < 1024 ? "aria-pressed" : "aria-selected", "true");
    if (width < 1024) await expect(updated).toBeFocused();

    const missing = recordEntry(page, width, "2026年6月14日 星期日，未录入，—");
    await missing.click();
    detail = recordDetail(page, width, "2026-06-14", "2026年6月14日 星期日");
    await expect(detail).toContainText("未录入");
    await detail.getByRole("link", { name: /^(修改这天记录|补记这天记录)$/ }).click();
    await expect(page).toHaveURL(/ledger\?date=2026-06-14$/);
    await page.getByLabel("当日营业额", { exact: true }).fill("350");
    await page.getByRole("button", { name: "补记历史记录", exact: true }).click();
    await expect(page).toHaveURL(width < 1024 ? /database\?date=2026-06-14$/ : /database$/);
    await expect(detail).toContainText("€350");
    const remove = detail.getByRole("button", { name: "删除记录", exact: true });
    await remove.click();
    const confirmation = page.getByRole("alertdialog", { name: "确认永久删除记录？" });
    await confirmation.getByRole("button", { name: "取消", exact: true }).click();
    await expect(remove).toBeFocused();
    await remove.click();
    await confirmation.getByRole("button", { name: "确认永久删除", exact: true }).click();
    await expect(confirmation.getByRole("button", { name: "正在删除…", exact: true })).toBeDisabled();
    releaseDelete();
    await expect(confirmation).not.toBeVisible();
    await expect.poll(() => refreshStarted).toBe(true);
    await expect(detail).toContainText("€350");
    releaseRefresh();
    await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
    await expect(missing).toBeVisible();
    await expect(missing).toHaveAttribute(width < 1024 ? "aria-pressed" : "aria-selected", "true");
    await expect(missing).toBeFocused();
    await expect(filters.getByLabel("月份", { exact: true })).toHaveValue("2026-06");

    const exportRequest = page.waitForRequest((request) => new URL(request.url()).pathname === "/api/database/1/export.xlsx");
    const download = page.waitForEvent("download");
    await filters.getByRole("button", { name: "导出当前范围", exact: true }).click();
    expect((await download).suggestedFilename()).toBe("营业记录-2026-06-01-2026-06-30.xlsx");
    const exportUrl = new URL((await exportRequest).url());
    expect(exportUrl.searchParams.get("start")).toBe("2026-06-01");
    expect(exportUrl.searchParams.get("end")).toBe("2026-06-30");
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    expect(fixture.contractErrors).toEqual([]);
  });
}

test("navigates, directly selects, and crosses years without entering a future month", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  const requests = { records: [] as RangeRequest[], charts: [] as RangeRequest[] };
  await mockBusinessRecords(page, requests);
  await page.goto("/database");

  const filters = page.getByRole("region", { name: "记录筛选" });
  const month = filters.getByLabel("月份", { exact: true });
  await expect(month).toHaveValue("2026-07");
  await expect(filters.getByRole("button", { name: "后一月" })).toBeDisabled();
  await expectLatestSynchronizedRange(requests, { storeId: 1, start: "2026-07-01", end: "2026-07-31" });

  const previous = filters.getByRole("button", { name: "前一月" });
  await previous.focus();
  await expect(previous).toBeFocused();
  await previous.press("Enter");
  await expect(month).toHaveValue("2026-06");
  await expectLatestSynchronizedRange(requests, { storeId: 1, start: "2026-06-01", end: "2026-06-30" });

  await month.fill("2026-01");
  await expectLatestSynchronizedRange(requests, { storeId: 1, start: "2026-01-01", end: "2026-01-31" });
  await previous.click();
  await expect(month).toHaveValue("2025-12");
  await expectLatestSynchronizedRange(requests, { storeId: 1, start: "2025-12-01", end: "2025-12-31" });

  const requestCount = requests.records.length;
  await month.fill("2026-08");
  await expect(filters.getByRole("alert")).toContainText("未来月份不可选择");
  await expect.poll(() => requests.records.length).toBe(requestCount);
});

test("recomputes the current month from the newly selected store timezone", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-08-01T00:30:00Z") });
  const requests = { records: [] as RangeRequest[], charts: [] as RangeRequest[] };
  await mockBusinessRecords(page, requests);
  await page.goto("/database");

  const filters = page.getByRole("region", { name: "记录筛选" });
  await expect(filters.getByLabel("月份", { exact: true })).toHaveValue("2026-08");
  await expectLatestSynchronizedRange(requests, { storeId: 1, start: "2026-08-01", end: "2026-08-31" });

  await page.getByTestId("desktop-store-picker").getByLabel("门店").selectOption("2");
  await expect(filters.getByLabel("月份", { exact: true })).toHaveValue("2026-07");
  await expect(filters.getByRole("button", { name: "后一月" })).toBeDisabled();
  await expectLatestSynchronizedRange(requests, { storeId: 2, start: "2026-07-01", end: "2026-07-31" });
});

test("uses month-bounded custom ranges and blocks reversed or future queries at 320px", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 320, height: 700 });
  const requests = { records: [] as RangeRequest[], charts: [] as RangeRequest[] };
  await mockBusinessRecords(page, requests);
  await page.goto("/database");

  const filters = page.getByRole("region", { name: "记录筛选" });
  await filters.getByRole("button", { name: "自定义范围" }).click();
  const start = filters.getByLabel("开始月份", { exact: true });
  const end = filters.getByLabel("结束月份", { exact: true });
  await start.fill("2026-05");
  await end.fill("2026-06");
  await expectLatestSynchronizedRange(requests, { storeId: 1, start: "2026-05-01", end: "2026-06-30" });

  await end.fill("2026-07");
  await expectLatestSynchronizedRange(requests, { storeId: 1, start: "2026-05-01", end: "2026-07-18" });

  const reversedCount = requests.records.length;
  await start.fill("2026-08");
  await expect(filters.getByRole("alert")).toContainText("未来月份不可选择");
  await expect.poll(() => requests.records.length).toBe(reversedCount);
  await start.fill("2026-07");
  await expectLatestSynchronizedRange(requests, { storeId: 1, start: "2026-07-01", end: "2026-07-18" });
  const validCount = requests.records.length;
  await end.fill("2026-06");
  await expect(filters.getByRole("alert")).toContainText("结束月份不能早于开始月份");
  await expect.poll(() => requests.records.length).toBe(validCount);

  await end.focus();
  await expect(end).toBeFocused();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(320);
});

test("loads every record page for a long custom month range", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  const requests = {
    records: [] as RangeRequest[],
    charts: [] as RangeRequest[],
    pagedRecords: [] as Array<RangeRequest & { page: number }>,
  };
  await mockBusinessRecords(page, requests);
  await page.goto("/database");

  const filters = page.getByRole("region", { name: "记录筛选" });
  await filters.getByRole("button", { name: "自定义范围" }).click();
  await filters.getByLabel("开始月份", { exact: true }).fill("2025-01");
  await filters.getByLabel("结束月份", { exact: true }).fill("2025-12");

  await expect.poll(() => requests.pagedRecords.filter((request) => (
    request.start === "2025-01-01" && request.end === "2025-12-31"
  )).map((request) => request.page)).toEqual([1, 2]);
});

for (const width of [390, 1280]) {
  test(`records request states stay truthful at ${width}px`, async ({ page }) => {
    await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
    await page.setViewportSize({ width, height: 800 });
    await mockBusinessRecords(page, { records: [], charts: [] });
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    let requests = 0;
    let allowSuccess = false;
    await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\/database\/1\/records/, async (route) => {
      requests += 1;
      if (requests === 1) {
        await pending;
        return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "offline" }) });
      }
      if (!allowSuccess) {
        return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "offline" }) });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 200 }) });
    });
    await page.goto("/database");
    await expect(page.getByText("正在加载记录…")).toBeVisible();
    await expect(page.getByText("未录入", { exact: true })).toHaveCount(0);
    release();
    await expect(page.getByText("加载记录失败，请重试。")).toBeVisible({ timeout: 15_000 });
    expect(requests).toBeGreaterThan(1);
    await expect(page.getByText("未录入", { exact: true })).toHaveCount(0);
    allowSuccess = true;
    await page.getByRole("button", { name: "重试", exact: true }).click();
    if (width < 1024) {
      await expect(page.getByRole("button", { name: /未录入/ }).first()).toBeVisible();
    } else {
      await expect(page.getByRole("table").getByText("未录入", { exact: true }).first()).toBeVisible();
    }
  });

  test(`late old-month response cannot create missing dates at ${width}px`, async ({ page }) => {
    await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
    await page.setViewportSize({ width, height: 800 });
    await mockBusinessRecords(page, { records: [], charts: [] });
    let releaseJuly!: () => void;
    const pendingJuly = new Promise<void>((resolve) => { releaseJuly = resolve; });
    let markJulyResponded!: () => void;
    const julyResponded = new Promise<void>((resolve) => { markJulyResponded = resolve; });
    await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\/database\/1\/records/, async (route) => {
      const start = new URL(route.request().url()).searchParams.get("start");
      if (start === "2026-07-01") await pendingJuly;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 200 }) });
      if (start === "2026-07-01") markJulyResponded();
    });
    await page.goto("/database");
    await expect(page.getByText("正在加载记录…")).toBeVisible();
    await page.getByRole("region", { name: "记录筛选" }).getByRole("button", { name: "前一月" }).click();
    const juneDate = width < 1024
      ? page.getByRole("button", { name: "2026年6月30日 星期二，未录入，—" })
      : page.getByRole("table").getByRole("row", { name: /2026年6月30日 星期二 未录入/ });
    await expect(juneDate).toBeVisible();
    releaseJuly();
    await julyResponded;
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(juneDate).toBeVisible();
    await expect(page.getByText("2026年7月17日 星期五")).toHaveCount(0);
  });
}
