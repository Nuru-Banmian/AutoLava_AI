import { expect, test, type Page } from "@playwright/test";

interface RangeRequest {
  storeId: number;
  start: string;
  end: string;
}

const stores = [
  { id: 1, name: "Kiritimati 门店", timezone: "Pacific/Kiritimati" },
  { id: 2, name: "Adak 门店", timezone: "America/Adak" },
];

async function mockBusinessRecords(page: Page, requests: { records: RangeRequest[]; charts: RangeRequest[] }) {
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
      requests.records.push({
        storeId: Number(recordMatch[1]),
        start: url.searchParams.get("start") ?? "",
        end: url.searchParams.get("end") ?? "",
      });
      return json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 200 });
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
