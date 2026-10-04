import { expect, test, type Page } from "@playwright/test";

const categories = Array.from({ length: 12 }, (_, index) => ({
  id: index + 1,
  name: `特别长的收入分类名称${index + 1}`,
  include_in_total: index < 6,
  is_active: true,
  sort_order: index + 1,
}));
const longStoreName = "特别特别特别特别特别特别特别特别特别特别特别特别特别特别特别特别长的门店名称";

function record(index: number) {
  const day = 17 - index;
  const date = `2026-07-${String(day).padStart(2, "0")}`;
  const now = `${date}T12:00:00`;
  const createdAt = `${date}T08:30:00`;
  const detailVariant = [
    { is_open: "营业", wash_count: 20 },
    { is_open: "休息", wash_count: 0 },
    { is_open: "提前休息", wash_count: null },
  ][index] ?? { is_open: "营业", wash_count: 20 - index };
  return {
    id: 100 + index,
    store_id: 1,
    date,
    daily_revenue: 100 - index,
    wash_count: detailVariant.wash_count,
    is_open: detailVariant.is_open,
    income_mode: "composed",
    weather: "晴",
    weather_auto: null,
    weather_code: null,
    temperature_max: null,
    temperature_min: null,
    precipitation: null,
    activity: index === 0 ? "会员日照常营业" : null,
    weather_edited: false,
    scanned: false,
    created_by: 1,
    updated_by: index === 0 ? 2 : 1,
    created_at: createdAt,
    updated_at: now,
    created_by_name: "小王",
    updated_by_name: index === 0 ? "小李" : "小王",
    bookkeeping_events: [
      { id: 2000 + index * 2, action: "created", actor_id: 1, actor_name: "小王", occurred_at: `${createdAt}Z`, timestamp_status: "utc" },
      { id: 2001 + index * 2, action: "updated", actor_id: index === 0 ? 2 : 1, actor_name: index === 0 ? "小李" : "小王", occurred_at: `${now}Z`, timestamp_status: "utc" },
    ],
    items: [{
      id: 1000 + index,
      category_id: 1,
      category_name: categories[0].name,
      include_in_total: true,
      sort_order: 1,
      amount: 100 - index,
      created_at: now,
      updated_at: now,
    }],
  };
}

async function mockResponsiveApi(page: Page, { washCountEnabled = true }: { washCountEnabled?: boolean } = {}) {
  const records = Array.from({ length: 16 }, (_, index) => record(index));
  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (value: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(value),
    });

    if (path === "/api/auth/me") return json({ id: 1, username: "operator", role: "user", is_owner: false });
    if (path === "/api/stores/accessible") {
      return json([{ id: 1, name: longStoreName, timezone: "Europe/Berlin", wash_count_enabled: washCountEnabled }]);
    }
    if (path === "/api/database/1/records") {
      const pageNumber = Number(url.searchParams.get("page"));
      const pageSize = Number(url.searchParams.get("page_size"));
      if (pageNumber !== 1 || pageSize !== 200) return json({ detail: "page_size must be 200" }, 400);
      return json({
        items: records,
        categories,
        sum_daily_revenue: 1480,
        total: records.length,
        page: 1,
        page_size: 200,
      });
    }
    if (path === "/api/charts/1") return json({
      kpis: {
        total_revenue: 100, record_days: 1, open_days: 1, average_revenue: 100,
        primary_categories: [], total_wash_count: null, average_ticket: null,
      },
      range: { start: "2026-07-01", end: "2026-07-17", bucket: "day" },
      comparison_kpis: {
        start: "2026-06-01", end: "2026-06-17", total_revenue: 80,
        open_days: 1, average_revenue: 80,
      },
      income_summary: {
        daily_ledger_revenue: 100, confirmed_settlement_income: 0,
        total_income: 100, includes_settlement_income: false,
      },
      classified_included_total: 100,
      daily: [{ date: "2026-07-14", revenue: 100 }],
      categories: categories.slice(0, 6).map((category, index) => ({
        category_id: category.id,
        category_name: category.name,
        amount: index === 0 ? 50 : 10,
      })),
      excluded_categories: categories.slice(6).map((category) => ({
        category_id: category.id,
        category_name: category.name,
        amount: 5,
      })),
      monthly: [{ month: "2026-07", revenue: 100, daily_ledger_revenue: 100, confirmed_settlement_income: 0, monthly_total_income: 100 }],
      weather: [],
      weekday: [],
    });
    return json({ detail: `unmocked ${request.method()} ${path}` }, 500);
  });
}

async function expectNativeMonthInput(input: ReturnType<Page["getByLabel"]>, expected: {
  ariaLabel: string;
  max: string;
}) {
  await expect(input).toHaveAttribute("type", "month");
  await expect(input).toHaveAttribute("aria-label", expected.ariaLabel);
  await expect(input).toHaveAttribute("max", expected.max);
  await expect.poll(() => input.evaluate((node) => node.getBoundingClientRect().height)).toBe(44);
}

test("desktop displays records beside their detail and gives analysis the full work area", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockResponsiveApi(page);
  await page.goto("/database");

  const detailWorkspace = page.locator("main").getByRole("complementary");
  const recordWorkspace = page.getByRole("table");
  await expect(page.getByRole("table")).toBeVisible();
  await expect(detailWorkspace).toBeVisible();
  const detailHeading = page.getByRole("heading", { name: "2026年7月17日 星期五" });
  await expect(detailHeading).toBeVisible();
  await expect(detailHeading.locator("..")).toContainText("营业");
  const detailSummary = page.getByRole("region", { name: "营业摘要" });
  await expect(detailSummary).toContainText("营业额€100");
  await expect(detailSummary).toContainText("天气晴");
  await expect(page.getByText("洗车 20 辆", { exact: true })).toBeVisible();
  await expect(page.getByText("洗车数量", { exact: true })).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1280);
  const [recordBox, detailBox] = await Promise.all([
    recordWorkspace.boundingBox(),
    detailWorkspace.boundingBox(),
  ]);
  expect(recordBox).not.toBeNull();
  expect(detailBox).not.toBeNull();
  expect(recordBox!.x + recordBox!.width).toBeLessThanOrEqual(detailBox!.x);
  expect(Math.abs(recordBox!.y - detailBox!.y)).toBeLessThanOrEqual(1);
  expect(recordBox!.width).toBeGreaterThan(300);
  expect(detailBox!.width).toBeGreaterThan(300);
  await expect(page.getByRole("heading", { name: "经营分析", exact: true })).not.toBeVisible();
  await page.getByRole("button", { name: "经营分析", exact: true }).click();
  const analysisWorkspace = page.getByRole("heading", { name: "经营分析", exact: true }).locator("../..");
  await expect(analysisWorkspace).toBeVisible();
  await expect(recordWorkspace).not.toBeVisible();
  const [analysisBox, mainBox] = await Promise.all([analysisWorkspace.boundingBox(), page.locator("main").boundingBox()]);
  expect(analysisBox!.width).toBeGreaterThan(mainBox!.width * 0.9);
  await expect(page.getByText("营业额趋势", { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1280);
});

test("weekday stays inside the date column at the narrow desktop breakpoint", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 1024, height: 900 });
  await mockResponsiveApi(page);
  await page.goto("/database");

  const row = page.getByRole("table").locator("tbody tr").first();
  await expect(row).toContainText("2026年7月17日 星期五");
  const [dateBox, statusBox, revenueBox] = await Promise.all([
    row.locator("td").nth(0).boundingBox(),
    row.locator("td").nth(1).boundingBox(),
    row.locator("td").nth(2).boundingBox(),
  ]);
  expect(dateBox).not.toBeNull();
  expect(statusBox).not.toBeNull();
  expect(revenueBox).not.toBeNull();
  expect(dateBox!.x + dateBox!.width).toBeLessThanOrEqual(statusBox!.x);
  expect(statusBox!.x + statusBox!.width).toBeLessThanOrEqual(revenueBox!.x);
  await expect(row.locator("td").nth(1)).toHaveText("营业");
  await expect(row.locator("td").nth(2)).toHaveText("€100");
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1024);
});

test("global store picker switches cleanly between mobile and desktop without header overflow", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await mockResponsiveApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/database");

  await expect(page.getByTestId("mobile-store-picker").getByRole("combobox", { name: "门店" })).toBeVisible();
  await expect(page.getByTestId("desktop-store-picker")).toBeHidden();
  const monthControls = page.getByLabel("月份导航").locator("button, input");
  await expect(monthControls).toHaveCount(3);
  for (const control of await monthControls.all()) {
    expect((await control.boundingBox())?.height).toBe(44);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);

  await page.setViewportSize({ width: 1280, height: 900 });
  const desktopPicker = page.getByTestId("desktop-store-picker");
  const brand = page.getByText("AutoLava AI", { exact: true });
  await expect(desktopPicker.getByRole("combobox", { name: "门店" })).toBeVisible();
  await expect(page.getByTestId("mobile-store-picker")).toBeHidden();
  const [pickerBox, brandBox] = await Promise.all([desktopPicker.boundingBox(), brand.boundingBox()]);
  expect(pickerBox).not.toBeNull();
  expect(brandBox).not.toBeNull();
  expect(pickerBox!.y).toBeGreaterThan(brandBox!.y + brandBox!.height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(1280);
});

test("320px record list, current-page detail, and analysis remain reachable without clipping", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 320, height: 700 });
  await mockResponsiveApi(page);
  await page.goto("/database");

  await expect(page.getByRole("heading", { name: "经营分析", exact: true })).not.toBeVisible();
  const recordFilters = page.getByRole("region", { name: "记录筛选" });
  await expect(recordFilters.getByTestId("record-filter-months")).toHaveCount(0);
  await expect(recordFilters.getByLabel("开始月份", { exact: true })).toHaveCount(0);
  await expect(recordFilters.getByLabel("结束月份", { exact: true })).toHaveCount(0);
  await recordFilters.getByRole("button", { name: "自定义范围" }).click();
  const dates = recordFilters.getByTestId("record-filter-months");
  const exportButton = recordFilters.getByRole("button", { name: "导出当前范围" });
  const [filterBox, datesBox, exportBox, startBox, endBox] = await Promise.all([
    recordFilters.boundingBox(), dates.boundingBox(), exportButton.boundingBox(),
    recordFilters.getByLabel("开始月份", { exact: true }).boundingBox(),
    recordFilters.getByLabel("结束月份", { exact: true }).boundingBox(),
  ]);
  expect(filterBox).not.toBeNull();
  expect(datesBox).not.toBeNull();
  expect(exportBox).not.toBeNull();
  expect(startBox).not.toBeNull();
  expect(endBox).not.toBeNull();
  expect(startBox!.y).toBe(endBox!.y);
  expect(startBox!.height).toBe(44);
  expect(endBox!.height).toBe(44);
  expect(startBox!.width).toBe(endBox!.width);
  expect(startBox!.x).toBeGreaterThanOrEqual(datesBox!.x);
  expect(endBox!.x + endBox!.width).toBeLessThanOrEqual(datesBox!.x + datesBox!.width);
  expect(exportBox!.y).toBeGreaterThanOrEqual(datesBox!.y + datesBox!.height + 8);
  expect(exportBox!.width).toBeGreaterThanOrEqual(120);
  expect(exportBox!.x + exportBox!.width).toBeLessThanOrEqual(filterBox!.x + filterBox!.width);

  await expect.poll(() => page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
    viewport: window.innerWidth,
  }))).toEqual({ document: 320, body: 320, viewport: 320 });
  await expect(page.getByRole("table")).toBeHidden();
  await expect(page.getByRole("heading", { name: "2026年7月17日 星期五" })).toHaveCount(0);

  const firstRow = page.locator('main button[aria-label^="2026年7月17日"]').first();
  await expect(firstRow).toHaveAccessibleName("2026年7月17日 星期五，营业，€100");
  const visibleFields = firstRow.locator(":scope > span");
  await expect(visibleFields).toHaveCount(3);
  await expect(visibleFields).toHaveText(["7月17日周五", "营业", "€100"]);
  await expect(firstRow.getByText("记账事件")).toHaveCount(0);
  const alignedRows = [
    firstRow,
    page.locator('main button[aria-label^="2026年7月16日"]').first(),
    page.locator('main button[aria-label^="2026年7月15日"]').first(),
  ];
  const alignedColumns = await Promise.all(alignedRows.map(async (row) => {
    const [status, revenue] = await Promise.all([
      row.locator(":scope > span").nth(1).boundingBox(),
      row.locator(":scope > span").nth(2).boundingBox(),
    ]);
    return { statusLeft: status?.x, revenueRight: (revenue?.x ?? 0) + (revenue?.width ?? 0) };
  }));
  expect(new Set(alignedColumns.map(({ statusLeft }) => Math.round(statusLeft ?? -1))).size).toBe(1);
  expect(new Set(alignedColumns.map(({ revenueRight }) => Math.round(revenueRight))).size).toBe(1);
  await firstRow.scrollIntoViewIfNeeded();
  const scrollBeforeOpen = await page.evaluate(() => window.scrollY);
  await firstRow.click();

  const detail = page.getByRole("region", { name: "2026-07-17 营业记录详情" });
  await expect(detail).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(recordFilters).not.toBeVisible();
  await expect(page.getByRole("group", { name: "营业记录视图" })).not.toBeVisible();
  const detailHeading = detail.getByRole("heading", { name: "2026年7月17日 星期五" });
  await expect(detailHeading).toBeVisible();
  await expect(detailHeading.locator("..")).toContainText("营业");
  const summary = detail.getByRole("region", { name: "营业摘要" });
  await expect(summary).toContainText("营业额€100");
  await expect(summary).toContainText("天气晴");
  await expect(detail.getByText("洗车 20 辆", { exact: true })).toBeVisible();
  await expect(detail.getByText("事件：会员日照常营业", { exact: true })).toBeVisible();
  const bookkeepingEvents = detail.getByRole("region", { name: "记账事件" });
  await expect(bookkeepingEvents).toContainText("小王创建记录");
  await expect(bookkeepingEvents).toContainText("2026年7月17日 10:30");
  await expect(bookkeepingEvents).toContainText("小李修改记录");
  await expect(bookkeepingEvents).toContainText("2026年7月17日 14:00");
  await expect(detail.getByText("洗车数量", { exact: true })).toHaveCount(0);
  const back = detail.getByRole("button", { name: "返回记录", exact: true });
  const [detailHeadingBox, backBox] = await Promise.all([detailHeading.boundingBox(), back.boundingBox()]);
  expect(backBox!.y).toBeLessThan(detailHeadingBox!.y + detailHeadingBox!.height);
  await expect(detailHeading).toBeFocused();
  await expect.poll(() => detailHeading.evaluate((node) => parseFloat(getComputedStyle(node).fontSize))).toBeGreaterThanOrEqual(16);
  await expect.poll(() => detail.getByText("€100", { exact: true }).first().evaluate((node) => getComputedStyle(node).fontSize)).toBe("18px");
  await expect.poll(() => detail.evaluate((node) => node.scrollWidth)).toBeLessThanOrEqual(320);
  await back.click();
  await expect(detail).toBeHidden();
  await expect(firstRow).toBeFocused();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(scrollBeforeOpen);
  await page.keyboard.press("Tab");
  const secondRow = page.locator('main button[aria-label^="2026年7月16日"]').first();
  await expect(secondRow).toBeFocused();
  const [focusedRowBox, focusedNavigationBox] = await Promise.all([
    secondRow.boundingBox(),
    page.getByRole("navigation", { name: "移动导航" }).boundingBox(),
  ]);
  expect(focusedRowBox).not.toBeNull();
  expect(focusedNavigationBox).not.toBeNull();
  expect(focusedRowBox!.y).toBeGreaterThanOrEqual(0);
  expect(focusedRowBox!.y + focusedRowBox!.height).toBeLessThanOrEqual(focusedNavigationBox!.y);

  await secondRow.click();
  const restDetail = page.getByRole("region", { name: "2026-07-16 营业记录详情" });
  await expect(restDetail.getByRole("heading", { name: "2026年7月16日 星期四" }).locator("..")).toContainText("休息");
  await expect(restDetail.getByText(/洗车 \d+ 辆/)).toHaveCount(0);
  await restDetail.getByRole("button", { name: "返回记录" }).click();
  await expect(secondRow).toBeFocused();

  const thirdRow = page.locator('main button[aria-label^="2026年7月15日"]').first();
  await thirdRow.click();
  const earlyCloseDetail = page.getByRole("region", { name: "2026-07-15 营业记录详情" });
  await expect(earlyCloseDetail.getByRole("heading", { name: "2026年7月15日 星期三" }).locator("..")).toContainText("提前休息");
  await expect(earlyCloseDetail.getByText(/洗车 \d+ 辆/)).toHaveCount(0);
  await earlyCloseDetail.getByRole("button", { name: "返回记录" }).click();
  await expect(thirdRow).toBeFocused();

  const pagination = page.getByRole("navigation", { name: "记录分页" });
  await page.getByRole("button", { name: "经营分析", exact: true }).click();
  await expect(pagination).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "经营分析", exact: true })).toBeVisible();

  await page.getByRole("region", { name: "收入分类" }).getByRole("button", { name: /展开收入分类/ }).click();
  await page.getByRole("region", { name: "其他数据" }).getByRole("button", { name: /展开其他数据/ }).click();
  const lastContent = page.getByText(categories.at(-1)!.name);
  const bottomNavigation = page.getByRole("navigation", { name: "移动导航" });
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect.poll(() => page.evaluate(() => Math.abs(
    window.scrollY - (document.documentElement.scrollHeight - window.innerHeight),
  ))).toBeLessThanOrEqual(1);
  await expect(lastContent).toBeVisible();
  const [contentBox, navigationBox] = await Promise.all([lastContent.boundingBox(), bottomNavigation.boundingBox()]);
  expect(contentBox).not.toBeNull();
  expect(navigationBox).not.toBeNull();
  expect(contentBox!.y + contentBox!.height).toBeLessThanOrEqual(navigationBox!.y);
  await expect.poll(() => page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
    viewport: window.innerWidth,
  }))).toEqual({ document: 320, body: 320, viewport: 320 });
});

test("record detail hides a positive wash count when the store setting is disabled", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockResponsiveApi(page, { washCountEnabled: false });
  await page.goto("/database");

  await expect(page.getByRole("heading", { name: "2026年7月17日 星期五" })).toBeVisible();
  await expect(page.getByText(/洗车 \d+ 辆/)).toHaveCount(0);
  await expect(page.getByRole("region", { name: "营业摘要" })).toBeVisible();
});

test("database desktop gives analysis full width with a compact trend and accessible custom months", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockResponsiveApi(page);
  await page.goto("/database");

  await page.getByRole("button", { name: "经营分析", exact: true }).click();
  const analysisWorkspace = page.getByRole("heading", { name: "经营分析", exact: true }).locator("../..");
  const trend = page.getByTestId("chart-panel-plot");
  await expect(analysisWorkspace).toBeVisible();
  await expect(trend).toBeVisible();
  const mainBox = await page.locator("main").boundingBox();
  await expect.poll(() => analysisWorkspace.evaluate((node) => node.getBoundingClientRect().width)).toBeGreaterThan(mainBox!.width * 0.9);
  await expect.poll(() => trend.evaluate((node) => node.getBoundingClientRect().height)).toBe(256);

  const recordFilters = page.getByRole("region", { name: "记录筛选" });
  const monthInput = recordFilters.getByLabel("月份", { exact: true });
  const customRangeButton = recordFilters.getByRole("button", { name: "自定义范围" });
  const exportButton = recordFilters.getByRole("button", { name: "导出当前范围" });
  const [monthBox, customRangeBox, exportBox] = await Promise.all([
    monthInput.boundingBox(),
    customRangeButton.boundingBox(),
    exportButton.boundingBox(),
  ]);
  expect(monthBox).not.toBeNull();
  expect(customRangeBox).not.toBeNull();
  expect(exportBox).not.toBeNull();
  expect(monthBox!.width).toBeLessThanOrEqual(160);
  expect(customRangeBox!.width).toBeLessThanOrEqual(144);
  expect(exportBox!.width).toBeLessThanOrEqual(160);
  await expect(recordFilters.getByLabel("营业状态")).toHaveCount(0);
  await recordFilters.getByRole("button", { name: "自定义范围" }).click();

  await expectNativeMonthInput(page.getByLabel("开始月份", { exact: true }), { ariaLabel: "开始月份", max: "2026-07" });
  await expectNativeMonthInput(page.getByLabel("结束月份", { exact: true }), { ariaLabel: "结束月份", max: "2026-07" });
});

test("database at 390px exposes all custom month inputs without horizontal overflow", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 390, height: 844 });
  await mockResponsiveApi(page);
  await page.goto("/database");

  const recordFilters = page.getByRole("region", { name: "记录筛选" });
  await expect(page.getByRole("heading", { name: "经营分析", exact: true })).not.toBeVisible();
  await expect(recordFilters.getByTestId("record-filter-months")).toHaveCount(0);
  await expect(recordFilters.getByLabel("开始月份", { exact: true })).toHaveCount(0);
  await expect(recordFilters.getByLabel("结束月份", { exact: true })).toHaveCount(0);
  await recordFilters.getByRole("button", { name: "自定义范围" }).click();
  const dates = recordFilters.getByTestId("record-filter-months");
  const exportButton = recordFilters.getByRole("button", { name: "导出当前范围" });
  const [filterBox, datesBox, exportBox, startBox, endBox] = await Promise.all([
    recordFilters.boundingBox(), dates.boundingBox(), exportButton.boundingBox(),
    recordFilters.getByLabel("开始月份", { exact: true }).boundingBox(),
    recordFilters.getByLabel("结束月份", { exact: true }).boundingBox(),
  ]);
  expect(filterBox).not.toBeNull();
  expect(datesBox).not.toBeNull();
  expect(exportBox).not.toBeNull();
  expect(startBox).not.toBeNull();
  expect(endBox).not.toBeNull();
  expect(startBox!.y).toBe(endBox!.y);
  expect(startBox!.height).toBe(44);
  expect(endBox!.height).toBe(44);
  expect(startBox!.width).toBe(endBox!.width);
  expect(startBox!.x).toBeGreaterThanOrEqual(datesBox!.x);
  expect(endBox!.x + endBox!.width).toBeLessThanOrEqual(datesBox!.x + datesBox!.width);
  expect(exportBox!.y).toBeGreaterThanOrEqual(datesBox!.y + datesBox!.height + 8);
  expect(exportBox!.width).toBeGreaterThanOrEqual(120);
  expect(exportBox!.x + exportBox!.width).toBeLessThanOrEqual(filterBox!.x + filterBox!.width);
  await recordFilters.getByRole("button", { name: "单月浏览" }).focus();
  await page.keyboard.press("Shift+Tab");
  const endDateInput = recordFilters.getByLabel("结束日期", { exact: true });
  await expect(endDateInput).toBeFocused();
  const [focusedInputBox, mobileNavigationBox] = await Promise.all([
    endDateInput.boundingBox(),
    page.getByRole("navigation", { name: "移动导航" }).boundingBox(),
  ]);
  expect(focusedInputBox).not.toBeNull();
  expect(mobileNavigationBox).not.toBeNull();
  expect(focusedInputBox!.y).toBeGreaterThanOrEqual(0);
  expect(focusedInputBox!.y + focusedInputBox!.height).toBeLessThanOrEqual(mobileNavigationBox!.y);
  await expectNativeMonthInput(page.getByLabel("开始月份", { exact: true }), { ariaLabel: "开始月份", max: "2026-07" });
  await expectNativeMonthInput(page.getByLabel("结束月份", { exact: true }), { ariaLabel: "结束月份", max: "2026-07" });
  await expect.poll(() => page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  }))).toEqual({ document: 390, viewport: 390 });
});
