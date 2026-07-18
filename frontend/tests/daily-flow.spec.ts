import { expect, test, type Page } from "@playwright/test";

const today = "2026-07-17";
const categories = Array.from({ length: 13 }, (_, index) => ({
  id: index + 1,
  name: `收入分类${index + 1}号超长名称`,
  include_in_total: index < 7,
  is_active: true,
  sort_order: index + 1,
}));

function snapshot(id: number, date: string, amount = `${id}.00`) {
  const now = `${date}T12:00:00`;
  return {
    id, store_id: 1, date, daily_revenue: amount, wash_count: null, is_open: "营业",
    income_mode: "composed", income_config_version_id: 4, row_version: 1,
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
      version_id: 4,
      version: 4,
      enabled: true,
      formula: categories.slice(0, 7).map((category) => category.name).join(" + "),
      created_at: `${today}T08:00:00`,
      items: categories.map((category, index) => ({ id: index + 20, category_id: category.id, ...category })),
    });
    if (path === `/api/weather/1/${today}`) return json({
      weather: null, weather_code: null, temperature_max: null, temperature_min: null, precipitation: null,
    });
    if (path === "/api/ledger/1/recent") return json(records.slice(0, 7));
    if (path === `/api/ledger/1/${today}` && request.method() === "GET") {
      const record = records.find((item) => item.date === today);
      return record ? json(record) : json({ detail: "not found" }, 404);
    }
    if (path === `/api/ledger/1/${today}` && request.method() === "PUT") {
      const body = request.postDataJSON() as {
        is_open: "营业" | "休息" | "天气停业";
        wash_count: number | null;
        weather: string | null;
        weather_edited: boolean;
        activity: string | null;
        items: { category_id: number; amount: string }[];
      };
      const amount = body.items.find((item) => item.category_id === 1)?.amount ?? "0.00";
      const saved = snapshot(999, today, amount);
      saved.items = body.items.map((item, index) => ({
        id: 9990 + index,
        category_id: item.category_id,
        category_name: categories.find((category) => category.id === item.category_id)!.name,
        include_in_total: categories.find((category) => category.id === item.category_id)!.include_in_total,
        sort_order: categories.find((category) => category.id === item.category_id)!.sort_order,
        amount: item.amount,
        created_at: `${today}T12:00:00`,
        updated_at: `${today}T12:00:00`,
      }));
      records = [saved, ...records.filter((item) => item.date !== today)];
      return json({ id: 999, date: today, daily_revenue: amount, row_version: 1 });
    }
    if (path === "/api/database/1/records") {
      const pageNumber = Number(url.searchParams.get("page"));
      const pageSize = Number(url.searchParams.get("page_size"));
      const start = url.searchParams.get("start") ?? "";
      const end = url.searchParams.get("end") ?? "";
      const filtered = records
        .filter((record) => record.date >= start && record.date <= end)
        .sort((left, right) => right.date.localeCompare(left.date));
      if (pageNumber === 1 && pageSize === 1 && start === today && end === today) {
        return json({
          items: filtered.slice(0, 1),
          categories,
          sum_daily_revenue: filtered[0]?.daily_revenue ?? "0.00",
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
        sum_daily_revenue: filtered.reduce((sum, record) => sum + Number(record.daily_revenue), 0).toFixed(2),
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
          total_revenue: "100.00", record_days: 1, open_days: 1, average_revenue: "100.00",
          primary_categories: [], total_wash_count: null, average_ticket: null,
        },
        range: { start, end, bucket },
        comparison_kpis: {
          start: "2026-06-01", end: "2026-06-17", total_revenue: "80.00",
          open_days: 1, average_revenue: "80.00",
        },
        classified_included_total: "100.00",
        daily: [{ date: "2026-07-14", revenue: "100.00" }],
        categories: categories.slice(0, 7).map((category, index) => ({
          category_id: category.id,
          category_name: category.name,
          amount: index === 0 ? "40.00" : "10.00",
        })),
        excluded_categories: categories.slice(7).map((category) => ({
          category_id: category.id,
          category_name: category.name,
          amount: "5.00",
        })),
        monthly: [{ month: "2026-07", revenue: "100.00" }],
        weather: [],
        weekday: [],
      });
    }
    return json({ detail: `unmocked ${request.method()} ${path}` }, 500);
  });

  return { databaseRequests, chartRequests, exportRequests };
}

function recordRows(page: Page, mobile: boolean) {
  return mobile
    ? page.locator('main button[aria-label^="2026年"]')
    : page.getByRole("table").locator("tbody tr");
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
    await page.getByLabel(categories[0].name).fill("100");
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
    await expect(detail.getByText("€100.00", { exact: true }).first()).toBeVisible();
    await expect(detail.getByRole("link", { name: "修改这天记录" })).toBeVisible();
    if (mobile) await page.getByRole("button", { name: "Close" }).click();

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

    await page.getByRole("button", { name: "上月", exact: true }).first().click();
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

    await page.getByRole("button", { name: "近 6 月" }).click();
    await expect(page.getByRole("button", { name: "近 6 月" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("第 1 / 2 页")).toBeVisible();
    await expect(recordRows(page, mobile).first()).toContainText("2026年6月30日");
    await expect.poll(() => requests.chartRequests.at(-1)?.searchParams.get("bucket")).toBe("month");
    await expect.poll(() => requests.databaseRequests.at(-1)?.searchParams.get("start")).toBe("2026-06-01");

    const included = page.getByRole("region", { name: "收入分类" });
    const excluded = page.getByRole("region", { name: "未计入总额" });
    await expect(included.getByText(categories[5].name)).toBeHidden();
    await expect(excluded.getByText(categories[12].name)).toBeHidden();
    await included.getByRole("button", { name: /展开收入分类/ }).click();
    await expect(included.getByText(categories[5].name)).toBeVisible();
    await expect(excluded.getByText(categories[12].name)).toBeHidden();
    await excluded.getByRole("button", { name: /展开未计入总额/ }).click();
    await expect(excluded.getByText(categories[12].name)).toBeVisible();
    await expect(included.getByRole("button", { name: "收起收入分类" })).toBeVisible();
    await expect(excluded.getByTestId("composition-proportion")).toHaveCount(0);
    await expect(page.getByText("未计入总额的金额不会计入总营业额、增幅或平均值。")).toBeVisible();

    await page.getByRole("button", { name: "导出当前范围" }).click();
    await expect.poll(() => requests.exportRequests.length).toBe(1);
    expect(requests.exportRequests[0].searchParams.get("start")).toBe("2026-06-01");
    expect(requests.exportRequests[0].searchParams.get("end")).toBe("2026-06-30");

  });
}
