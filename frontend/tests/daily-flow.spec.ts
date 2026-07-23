import { expect, test, type Page } from "@playwright/test";

const today = "2026-07-17";
const categories = Array.from({ length: 13 }, (_, index) => ({
  id: index + 1,
  name: `收入分类${index + 1}号超长名称`,
  include_in_total: index < 7,
  is_active: true,
  sort_order: index + 1,
}));

function snapshot(id: number, date: string, amount = id) {
  const now = `${date}T12:00:00`;
  return {
    id, store_id: 1, date, daily_revenue: amount, wash_count: null, is_open: "营业",
    income_mode: "composed",
    weather: null, weather_auto: null, weather_code: null, temperature_max: null,
    temperature_min: null, precipitation: null, activity: null, weather_edited: false,
    scanned: false, created_by: 1, updated_by: 1, created_at: now, updated_at: now,
    items: [{
      id: id * 10,
      category_id: 1,
      category_name: categories[0].name,
      include_in_total: true,
      sort_order: 1,
      amount,
      created_at: now,
      updated_at: now,
    }],
  };
}

function monthRecords(month: "06" | "07", count: number, idBase: number) {
  return Array.from({ length: count }, (_, index) => {
    const day = count - index;
    return snapshot(idBase + index, `2026-${month}-${String(day).padStart(2, "0")}`);
  });
}

async function mockMergedFlow(page: Page) {
  let records = [...monthRecords("07", 16, 100), ...monthRecords("06", 18, 200)];
  const databaseRequests: URL[] = [];
  const chartRequests: URL[] = [];
  const exportRequests: URL[] = [];
  const ledgerWrites: { date: string; body: { items: { category_id: number; amount: number }[] } }[] = [];
  const ledgerDeletes: string[] = [];

  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (value: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(value),
    });

    if (path === "/api/auth/me") return json({ id: 1, username: "administrator", role: "admin", is_owner: true });
    if (path === "/api/stores/accessible") return json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }]);
    if (path === "/api/dashboard/1") return json([]);
    if (path === "/api/income-config/1/current") return json({
      store_id: 1,
      enabled: true,
      formula: categories.slice(0, 7).map((category) => category.name).join(" + "),
      items: categories.map((category) => ({ ...category, store_id: 1, archived_at: null })),
    });
    if (/^\/api\/weather\/1\/\d{4}-\d{2}-\d{2}$/.test(path)) return json({
      weather: null, weather_code: null, temperature_max: null, temperature_min: null, precipitation: null,
    });
    if (path === "/api/ledger/1/recent") return json(records.slice(0, 7));
    const ledgerMatch = path.match(/^\/api\/ledger\/1\/(\d{4}-\d{2}-\d{2})$/);
    if (ledgerMatch && request.method() === "GET") {
      const record = records.find((item) => item.date === ledgerMatch[1]);
      return record ? json(record) : json({ detail: "not found" }, 404);
    }
    if (ledgerMatch && request.method() === "PUT") {
      const targetDate = ledgerMatch[1];
      const body = request.postDataJSON() as {
        is_open: "营业" | "休息" | "天气停业";
        wash_count: number | null;
        weather: string | null;
        weather_edited: boolean;
        activity: string | null;
        items: { category_id: number; amount: number }[];
      };
      ledgerWrites.push({ date: targetDate, body });
      const amount = body.items.find((item) => item.category_id === 1)?.amount ?? 0;
      const existing = records.find((item) => item.date === targetDate);
      const saved = snapshot(existing?.id ?? 999, targetDate, amount);
      saved.items = body.items.map((item, index) => ({
        id: saved.id * 10 + index,
        category_id: item.category_id,
        category_name: categories.find((category) => category.id === item.category_id)!.name,
        include_in_total: categories.find((category) => category.id === item.category_id)!.include_in_total,
        sort_order: categories.find((category) => category.id === item.category_id)!.sort_order,
        amount: item.amount,
        created_at: `${targetDate}T12:00:00`,
        updated_at: `${targetDate}T12:00:00`,
      }));
      records = [saved, ...records.filter((item) => item.date !== targetDate)]
        .sort((left, right) => right.date.localeCompare(left.date));
      return json({ id: saved.id, date: targetDate, daily_revenue: amount });
    }
    if (ledgerMatch && request.method() === "DELETE") {
      ledgerDeletes.push(ledgerMatch[1]);
      records = records.filter((item) => item.date !== ledgerMatch[1]);
      return route.fulfill({ status: 204 });
    }
    if (path === "/api/database/1/records") {
      const pageNumber = Number(url.searchParams.get("page"));
      const pageSize = Number(url.searchParams.get("page_size"));
      const start = url.searchParams.get("start") ?? "";
      const end = url.searchParams.get("end") ?? "";
      const filtered = records
        .filter((record) => record.date >= start && record.date <= end)
        .sort((left, right) => right.date.localeCompare(left.date));
      if (pageNumber === 1 && pageSize === 1 && start === end) {
        return json({
          items: filtered.slice(0, 1),
          categories,
          sum_daily_revenue: filtered[0]?.daily_revenue ?? 0,
          total: filtered.length,
          page: 1,
          page_size: 1,
        });
      }
      databaseRequests.push(url);
      if (pageNumber !== 1 || pageSize !== 200) return json({ detail: "invalid paging contract" }, 400);
      return json({
        items: filtered,
        categories,
        sum_daily_revenue: filtered.reduce((sum, record) => sum + record.daily_revenue, 0),
        total: filtered.length,
        page: 1,
        page_size: 200,
      });
    }
    if (path === "/api/database/1/export.xlsx") {
      exportRequests.push(url);
      return route.fulfill({
        status: 200,
        contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        body: "acceptance workbook",
      });
    }
    if (path === "/api/charts/1") {
      chartRequests.push(url);
      const start = url.searchParams.get("start") ?? "2026-07-01";
      const end = url.searchParams.get("end") ?? today;
      const bucket = url.searchParams.get("bucket") === "month" ? "month" : "day";
      return json({
        kpis: {
          total_revenue: 100, record_days: 1, open_days: 1, average_revenue: 100,
          primary_categories: [], total_wash_count: null, average_ticket: null,
        },
        range: { start, end, bucket },
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
        categories: categories.slice(0, 7).map((category, index) => ({
          category_id: category.id,
          category_name: category.name,
          amount: index === 0 ? 40 : 10,
        })),
        excluded_categories: categories.slice(7).map((category) => ({
          category_id: category.id,
          category_name: category.name,
          amount: 5,
        })),
        monthly: [{ month: "2026-07", revenue: 100, daily_ledger_revenue: 100, confirmed_settlement_income: 0, monthly_total_income: 100 }],
        weather: [],
        weekday: [],
      });
    }
    return json({ detail: `unmocked ${request.method()} ${path}` }, 500);
  });

  return { databaseRequests, chartRequests, exportRequests, ledgerWrites, ledgerDeletes };
}

function recordRows(page: Page, mobile: boolean) {
  return mobile
    ? page.locator('main button[aria-label^="2026年"]')
    : page.getByRole("table").locator("tbody tr");
}

async function fillNewRecordAmounts(page: Page, firstAmount: string) {
  await page.getByLabel(categories[0].name).fill(firstAmount);
  for (const category of categories.slice(1)) {
    await page.getByLabel(category.name).fill("0");
  }
}

for (const viewport of [
  { name: "desktop", width: 1280, height: 900, desktop: true },
  { name: "390px", width: 390, height: 844, desktop: false },
  { name: "320px", width: 320, height: 700, desktop: false },
]) {
  test(`${viewport.name}: daily ledger uses the responsive wide-card form`, async ({ page }) => {
    await page.clock.install({ time: new Date(`${today}T12:00:00Z`) });
    await page.setViewportSize(viewport);
    const flow = await mockMergedFlow(page);
    await page.goto(`/ledger?date=${today}`);

    const card = page.getByRole("region", { name: "每日台账录入" });
    const statusAndWeatherGroup = page.getByRole("group", { name: "状态与天气" });
    const status = page.getByLabel("状态", { exact: true });
    const weather = page.getByRole("combobox", { name: "天气" });
    const firstIncome = page.getByLabel(categories[0].name);
    const secondIncome = page.getByLabel(categories[1].name);
    await expect(card).toBeVisible();
    await expect(page.getByRole("heading", { name: "最近七天" })).toHaveCount(0);

    const [mainBox, cardBox, statusAndWeatherBox, statusBox, weatherBox, firstIncomeBox, secondIncomeBox] = await Promise.all([
      page.locator("main").boundingBox(), card.boundingBox(), statusAndWeatherGroup.boundingBox(), status.boundingBox(), weather.boundingBox(),
      firstIncome.boundingBox(), secondIncome.boundingBox(),
    ]);
    for (const box of [mainBox, cardBox, statusAndWeatherBox, statusBox, weatherBox, firstIncomeBox, secondIncomeBox]) expect(box).not.toBeNull();
    expect(statusBox!.height).toBeGreaterThanOrEqual(44);
    expect(weatherBox!.height).toBeGreaterThanOrEqual(44);
    expect(firstIncomeBox!.height).toBeGreaterThanOrEqual(44);

    if (viewport.desktop) {
      expect(cardBox!.width).toBeGreaterThanOrEqual(800);
      expect(cardBox!.width).toBeLessThanOrEqual(900);
      expect(Math.abs(cardBox!.x + cardBox!.width / 2 - (mainBox!.x + mainBox!.width / 2))).toBeLessThanOrEqual(1);
      expect(Math.abs(statusBox!.y - weatherBox!.y)).toBeLessThanOrEqual(1);
      expect(Math.abs(firstIncomeBox!.y - secondIncomeBox!.y)).toBeLessThanOrEqual(1);
    } else {
      expect(weatherBox!.y).toBeGreaterThanOrEqual(statusBox!.y + statusBox!.height + 8);
      expect(secondIncomeBox!.y).toBeGreaterThanOrEqual(firstIncomeBox!.y + firstIncomeBox!.height + 8);
      await expect.poll(() => page.evaluate(() => ({
        body: document.body.scrollWidth,
        document: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
      }))).toEqual({ body: viewport.width, document: viewport.width, viewport: viewport.width });
    }

    await fillNewRecordAmounts(page, "100");
    await expect(page.getByText("合计 €100", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "保存今日记录" }).click();
    await expect(page.getByRole("status")).toContainText("保存成功");
    expect(flow.ledgerWrites.at(-1)).toMatchObject({ date: today });
  });
}

for (const viewport of [
  { name: "desktop", width: 1280, height: 900 },
  { name: "320px", width: 320, height: 700 },
]) {
  test(`${viewport.name}: merged record and analysis workflow`, async ({ page }) => {
    const mobile = viewport.width === 320;
    await page.clock.install({ time: new Date(`${today}T12:00:00Z`) });
    await page.setViewportSize(viewport);
    const requests = await mockMergedFlow(page);

    await page.goto(`/ledger?date=${today}`);
    await fillNewRecordAmounts(page, "100");
    await page.getByRole("button", { name: "保存今日记录" }).click();
    await expect(page.getByRole("status")).toContainText("保存成功");

    const navigation = page.getByRole("navigation", { name: mobile ? "移动导航" : "主导航" });
    await navigation.getByRole("link", { name: mobile ? "记录" : "营业记录" }).click();
    await expect(page).toHaveURL(/\/database$/);
    await expect(page.getByRole("heading", { name: "营业记录" })).toBeVisible();
    await expect(page.getByText("第 1 / 2 页")).toBeVisible();

    const firstCurrentRow = recordRows(page, mobile).first();
    await expect(firstCurrentRow).toContainText("2026年7月17日");
    if (mobile) await firstCurrentRow.click();
    const detail = mobile
      ? page.getByRole("dialog", { name: "2026-07-17 营业记录详情" })
      : page.getByRole("heading", { name: "2026年7月17日" }).locator("../..");
    await expect(detail.getByText("€100", { exact: true }).first()).toBeVisible();
    await expect(detail.getByRole("link", { name: "修改这天记录" })).toBeVisible();
    if (mobile) {
      const deleteButton = detail.getByRole("button", { name: "删除记录" });
      await deleteButton.focus();
      await page.keyboard.press("Enter");
      const deleteDialog = page.getByRole("alertdialog", { name: "确认永久删除记录？" });
      await expect(deleteDialog).toBeVisible();
      await expect(deleteDialog).toContainText("删除后无法恢复。");
      const cancelDelete = deleteDialog.getByRole("button", { name: "取消" });
      await expect(cancelDelete).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(deleteDialog).toBeHidden();
      await expect(deleteButton).toBeFocused();
      expect(requests.ledgerDeletes).toEqual([]);
      await page.getByRole("button", { name: "Close" }).click();
    }

    await page.getByRole("button", { name: "下一页" }).click();
    await expect(page.getByText("第 2 / 2 页")).toBeVisible();
    const pageTwoFirst = recordRows(page, mobile).first();
    await expect(pageTwoFirst).toContainText("2026年7月2日");
    await pageTwoFirst.click();
    if (mobile) {
      await expect(pageTwoFirst).toHaveAttribute("aria-pressed", "true");
      await page.getByRole("button", { name: "Close" }).click();
    } else {
      await expect(page.getByRole("heading", { name: "2026年7月2日" })).toBeVisible();
    }

    await page.getByRole("button", { name: "前一月", exact: true }).click();
    await expect(page.getByText("第 1 / 2 页")).toBeVisible();
    const previousMonthFirst = recordRows(page, mobile).first();
    await expect(previousMonthFirst).toContainText("2026年6月30日");
    await previousMonthFirst.click();
    if (mobile) {
      await expect(previousMonthFirst).toHaveAttribute("aria-pressed", "true");
      await page.getByRole("button", { name: "Close" }).click();
    } else {
      await expect(page.getByRole("heading", { name: "2026年6月30日" })).toBeVisible();
    }

    await expect(page.getByText("第 1 / 2 页")).toBeVisible();
    await expect(recordRows(page, mobile).first()).toContainText("2026年6月30日");
    await expect.poll(() => requests.chartRequests.at(-1)?.searchParams.get("start")).toBe("2026-06-01");
    await expect.poll(() => requests.chartRequests.at(-1)?.searchParams.get("end")).toBe("2026-06-30");
    await expect.poll(() => requests.chartRequests.at(-1)?.searchParams.get("bucket")).toBe("day");
    await expect.poll(() => requests.databaseRequests.at(-1)?.searchParams.get("start")).toBe("2026-06-01");

    const included = page.getByRole("region", { name: "收入分类" });
    const excluded = page.getByRole("region", { name: "其他数据" });
    await expect(included.getByText(categories[5].name)).toBeHidden();
    await expect(excluded.getByText(categories[12].name)).toBeHidden();
    await included.getByRole("button", { name: /展开收入分类/ }).click();
    await expect(included.getByText(categories[5].name)).toBeVisible();
    await expect(excluded.getByText(categories[12].name)).toBeHidden();
    await excluded.getByRole("button", { name: /展开其他数据/ }).click();
    await expect(excluded.getByText(categories[12].name)).toBeVisible();
    await expect(included.getByRole("button", { name: "收起收入分类" })).toBeVisible();
    await expect(excluded.getByTestId("composition-proportion")).toHaveCount(0);
    await expect(page.getByText(/未计入总额|历史总额记录/)).toHaveCount(0);

    await page.getByRole("button", { name: "导出当前范围" }).click();
    await expect.poll(() => requests.exportRequests.length).toBe(1);
    expect(requests.exportRequests[0].searchParams.get("start")).toBe("2026-06-01");
    expect(requests.exportRequests[0].searchParams.get("end")).toBe("2026-06-30");

  });
}

test("desktop: multi-date ledger snapshots, markers, dirty guards, and permanent deletion", async ({ page }) => {
  await page.clock.install({ time: new Date(`${today}T12:00:00Z`) });
  await page.setViewportSize({ width: 1280, height: 900 });
  const flow = await mockMergedFlow(page);

  await page.goto(`/ledger?date=${today}`);
  await fillNewRecordAmounts(page, "123");
  await page.getByRole("button", { name: "保存今日记录" }).click();
  await expect(page.getByRole("status")).toContainText("保存成功");

  await page.getByRole("button", { name: "选择台账日期：2026年7月17日" }).click();
  const july15 = page.getByRole("button", { name: "2026年7月15日，已有记录" });
  const july16 = page.getByRole("button", { name: "2026年7月16日，已有记录" });
  await expect(july15).toHaveAttribute("data-recorded", "true");
  await expect(july16).toHaveAttribute("data-recorded", "true");
  await expect(july15.locator("span")).toHaveClass(/bg-primary/);
  await july15.click();

  await expect(page).toHaveURL(/date=2026-07-15/);
  await expect(page.getByLabel(categories[0].name)).toHaveValue("101");
  await page.getByLabel(categories[0].name).fill("215");
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.getByRole("status")).toContainText("保存成功");
  expect(flow.ledgerWrites.map(({ date, body }) => ({
    date,
    amount: body.items.find((item) => item.category_id === 1)?.amount,
  }))).toEqual([
    { date: "2026-07-17", amount: 123 },
    { date: "2026-07-15", amount: 215 },
  ]);

  await page.getByRole("button", { name: "选择台账日期：2026年7月15日" }).click();
  await page.getByRole("button", { name: "2026年7月16日，已有记录" }).click();
  await expect(page.getByRole("button", { name: "选择台账日期：2026年7月16日" })).toBeVisible();
  await expect(page.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toHaveCount(0);
  await expect(page.getByLabel(categories[0].name)).toHaveValue("100");

  await page.getByLabel(categories[0].name).fill("333");
  await page.getByRole("button", { name: "选择台账日期：2026年7月16日" }).click();
  await page.getByRole("button", { name: "2026年7月15日，已有记录" }).click();
  const dirtyGuard = page.getByRole("alertdialog", { name: "放弃未保存的修改？" });
  await expect(dirtyGuard).toBeVisible();
  await dirtyGuard.getByRole("button", { name: "继续编辑" }).click();
  await expect(page.getByLabel(categories[0].name)).toHaveValue("333");
  await page.getByRole("button", { name: "选择台账日期：2026年7月16日" }).click();
  await page.getByRole("button", { name: "2026年7月15日，已有记录" }).click();
  await dirtyGuard.getByRole("button", { name: "放弃修改" }).click();

  const navigation = page.getByRole("navigation", { name: "主导航" });
  await navigation.getByRole("link", { name: "营业记录" }).click();
  const targetRow = page.getByRole("table").locator("tbody tr").filter({ hasText: "2026年7月15日" });
  await targetRow.click();
  const chartRequestsBeforeDelete = flow.chartRequests.length;
  const deleteButton = page.getByRole("button", { name: "删除记录" });
  await deleteButton.focus();
  await page.keyboard.press("Enter");
  const deleteDialog = page.getByRole("alertdialog", { name: "确认永久删除记录？" });
  await expect(deleteDialog).toContainText("删除后无法恢复。");
  await expect(deleteDialog.getByRole("button", { name: "取消" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(deleteDialog.getByRole("button", { name: "确认永久删除" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(() => flow.ledgerDeletes).toContain("2026-07-15");
  await expect(page.getByRole("table").locator("tbody tr").filter({ hasText: "2026年7月15日" })).toContainText("未录入");
  await expect.poll(() => flow.chartRequests.length).toBeGreaterThan(chartRequestsBeforeDelete);
  await expect(page.getByRole("heading", { name: "2026年7月15日" })).toHaveCount(0);

  await navigation.getByRole("link", { name: "每日记账" }).click();
  await page.getByRole("button", { name: "选择台账日期：2026年7月17日" }).click();
  await expect(page.getByRole("button", { name: "2026年7月15日" })).not.toHaveAttribute("data-recorded");
});
