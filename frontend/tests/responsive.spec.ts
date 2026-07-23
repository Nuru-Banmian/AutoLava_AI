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
  return {
    id: 100 + index,
    store_id: 1,
    date,
    daily_revenue: 100 - index,
    wash_count: 20 - index,
    is_open: "营业",
    income_mode: "composed",
    weather: "晴",
    weather_auto: null,
    weather_code: null,
    temperature_max: null,
    temperature_min: null,
    precipitation: null,
    activity: null,
    weather_edited: false,
    scanned: false,
    created_by: 1,
    updated_by: 1,
    created_at: now,
    updated_at: now,
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

async function mockResponsiveApi(page: Page) {
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
    if (path === "/api/stores/accessible") return json([{ id: 1, name: longStoreName, timezone: "Europe/Berlin" }]);
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
  await expect.poll(() => input.evaluate((node) => node.getBoundingClientRect().height)).toBe(40);
}

test("desktop record and analysis workspaces share the viewport without outer scrolling", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockResponsiveApi(page);
  await page.goto("/database");

  const analysisWorkspace = page.locator("main").getByRole("complementary");
  const recordWorkspace = analysisWorkspace.locator("xpath=preceding-sibling::*[1]");
  await expect(page.getByRole("table")).toBeVisible();
  await expect(analysisWorkspace).toBeVisible();
  await expect(page.getByRole("heading", { name: "2026年7月17日" })).toBeVisible();
  const [recordBox, analysisBox] = await Promise.all([
    recordWorkspace.boundingBox(),
    analysisWorkspace.boundingBox(),
  ]);
  expect(recordBox).not.toBeNull();
  expect(analysisBox).not.toBeNull();
  expect(Math.abs(recordBox!.y - analysisBox!.y)).toBeLessThanOrEqual(1);
  expect(Math.abs(recordBox!.y + recordBox!.height - analysisBox!.y - analysisBox!.height)).toBeLessThanOrEqual(1);
  expect(Math.abs(analysisBox!.y + analysisBox!.height - (900 - 24))).toBeLessThanOrEqual(1);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollHeight)).toBeLessThanOrEqual(900);

  await expect.poll(() => analysisWorkspace.evaluate((node) => ({
    overflowY: getComputedStyle(node).overflowY,
    independentlyScrollable: node.scrollHeight > node.clientHeight,
  }))).toEqual({ overflowY: "auto", independentlyScrollable: true });

  const outerScrollBefore = await page.evaluate(() => window.scrollY);
  await analysisWorkspace.evaluate((node) => node.scrollTo({ top: node.scrollHeight }));
  const analysisCard = analysisWorkspace.locator(":scope > *").last();
  await expect.poll(async () => {
    const [workspaceBox, cardBox] = await Promise.all([
      analysisWorkspace.boundingBox(),
      analysisCard.boundingBox(),
    ]);
    return analysisWorkspace.evaluate((node, bottomGap) => ({
      atEnd: Math.abs(node.scrollTop - (node.scrollHeight - node.clientHeight)) <= 1,
      bottomGap,
    }), Math.round((workspaceBox?.y ?? 0) + (workspaceBox?.height ?? 0) - (cardBox?.y ?? 0) - (cardBox?.height ?? 0)));
  }).toEqual({ atEnd: true, bottomGap: 0 });
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(outerScrollBefore);
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
    expect((await control.boundingBox())?.height).toBe(40);
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

test("320px record list, bottom sheet, and analysis remain reachable without clipping", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 320, height: 700 });
  await mockResponsiveApi(page);
  await page.goto("/database");

  const analysisWorkspace = page.locator("main").getByRole("complementary");
  await expect.poll(() => analysisWorkspace.evaluate((node) => ({
    overflowY: getComputedStyle(node).overflowY,
    expandsToContent: node.scrollHeight === node.clientHeight,
  }))).toEqual({ overflowY: "visible", expandsToContent: true });
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
  expect(startBox!.height).toBe(40);
  expect(endBox!.height).toBe(40);
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
  await expect(page.getByRole("heading", { name: "2026年7月17日" })).toHaveCount(0);

  const firstRow = page.locator('main button[aria-label^="2026年7月17日"]').first();
  await expect(firstRow).toHaveAccessibleName("2026年7月17日，营业，€100");
  const visibleFields = firstRow.locator(":scope > span");
  await expect(visibleFields).toHaveCount(3);
  await expect(visibleFields).toHaveText(["2026年7月17日", "营业", "€100"]);
  await firstRow.scrollIntoViewIfNeeded();
  const scrollBeforeOpen = await page.evaluate(() => window.scrollY);
  await firstRow.click();

  const sheet = page.getByRole("dialog", { name: "2026-07-17 营业记录详情" });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("heading", { name: "2026年7月17日" })).toBeVisible();
  await expect.poll(() => sheet.evaluate((node) => ({
    position: getComputedStyle(node).position,
    top: node.getBoundingClientRect().top,
    bottom: getComputedStyle(node).bottom,
    height: node.getBoundingClientRect().height,
  }))).toEqual({ position: "fixed", top: 16, bottom: "0px", height: 684 });
  await expect.poll(() => sheet.getByRole("heading", { name: "2026年7月17日" }).evaluate((node) => getComputedStyle(node).fontSize)).toBe("24px");
  await expect.poll(() => sheet.getByText("€100", { exact: true }).first().evaluate((node) => getComputedStyle(node).fontSize)).toBe("18px");
  await sheet.getByRole("button", { name: "Close" }).click();
  await expect(sheet).toBeHidden();
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

  const pagination = page.getByRole("navigation", { name: "记录分页" });
  const analysis = page.getByRole("heading", { name: "经营分析" });
  const [paginationBox, analysisBox] = await Promise.all([pagination.boundingBox(), analysis.boundingBox()]);
  expect(paginationBox).not.toBeNull();
  expect(analysisBox).not.toBeNull();
  expect(analysisBox!.y).toBeGreaterThanOrEqual(paginationBox!.y + paginationBox!.height);

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

test("database desktop keeps the wide analysis rail, compact trend, and accessible custom months", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-17T12:00:00Z") });
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockResponsiveApi(page);
  await page.goto("/database");

  const analysisRail = page.locator("main > section > div > aside");
  await expect(analysisRail).toHaveCount(1);
  const trend = page.getByTestId("chart-panel-plot");
  await expect(analysisRail).toBeVisible();
  await expect(trend).toBeVisible();
  await expect.poll(() => analysisRail.evaluate((node) => node.getBoundingClientRect().width)).toBeGreaterThanOrEqual(480);
  await expect.poll(() => analysisRail.evaluate((node) => node.getBoundingClientRect().width)).toBeLessThanOrEqual(512);
  await expect.poll(() => trend.evaluate((node) => node.getBoundingClientRect().height)).toBe(256);

  const recordFilters = page.getByRole("region", { name: "记录筛选" });
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
  const analysisRail = page.locator("main > section > div > aside");
  await expect(analysisRail).toHaveCount(1);
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
  expect(startBox!.height).toBe(40);
  expect(endBox!.height).toBe(40);
  expect(startBox!.width).toBe(endBox!.width);
  expect(startBox!.x).toBeGreaterThanOrEqual(datesBox!.x);
  expect(endBox!.x + endBox!.width).toBeLessThanOrEqual(datesBox!.x + datesBox!.width);
  expect(exportBox!.y).toBeGreaterThanOrEqual(datesBox!.y + datesBox!.height + 8);
  expect(exportBox!.width).toBeGreaterThanOrEqual(120);
  expect(exportBox!.x + exportBox!.width).toBeLessThanOrEqual(filterBox!.x + filterBox!.width);
  await recordFilters.getByRole("button", { name: "单月浏览" }).focus();
  await page.keyboard.press("Shift+Tab");
  const endMonthInput = recordFilters.getByLabel("结束月份", { exact: true });
  await expect(endMonthInput).toBeFocused();
  const [focusedInputBox, mobileNavigationBox] = await Promise.all([
    endMonthInput.boundingBox(),
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
