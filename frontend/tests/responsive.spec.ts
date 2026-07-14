import { expect, test, type Page } from "@playwright/test";

const categories = Array.from({ length: 8 }, (_, index) => ({ id: index + 1, name: `收入分类${index + 1}`, include_in_total: index < 2, is_active: true, sort_order: index + 1 }));
const emptyDb = { items: [], categories, sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 50 };
async function mockApi(page: Page) {
  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const url = new URL(route.request().url()); const path = url.pathname;
    const json = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
    if (path === "/api/auth/me") return json({ id: 1, username: "operator", role: "user" });
    if (path === "/api/stores/accessible") return json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }]);
    if (path.includes("/api/database/1/records")) return json(emptyDb);
    if (path.includes("/api/database/1/history")) return json([]);
    if (path.includes("/api/ledger/1/recent")) return json([]);
    if (path.startsWith("/api/ledger/1/")) return json({ detail: "not found" }, 404);
    if (path.startsWith("/api/weather/1/")) return json({ weather: null, weather_code: null, temperature_max: null, temperature_min: null, precipitation: null });
    if (path === "/api/charts/1") return json({ kpis: { total_revenue: "100", record_days: 1, open_days: 1, primary_categories: [{ category_id: 1, category_name: "收入分类1", amount: "100" }], total_wash_count: null, average_ticket: null }, daily: [{ date: "2026-07-01", revenue: "100" }], categories: [{ category_id: 1, category_name: "收入分类1", amount: "100" }], monthly: [{ month: "2026-07", revenue: "100" }], weather: [{ weather: "晴", average_revenue: "100" }], weekday: [{ weekday: 0, average_revenue: "100" }] });
    if (path === "/api/dashboard/1") return json([]);
    return json({ detail: `unmocked ${path}` }, 500);
  });
}

test("mobile ledger fits viewport and uses bottom navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await mockApi(page); await page.goto("/ledger");
  await expect(page.getByRole("heading", { name: "每日台账" })).toBeVisible(); await expect(page.getByRole("navigation", { name: "移动导航" })).toBeVisible(); await expect(page.getByRole("navigation", { name: "主导航" })).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("database owns horizontal table scrolling on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await mockApi(page); await page.goto("/database");
  const scroller = page.getByTestId("record-table-scroll"); await expect(scroller).toBeVisible(); expect(await scroller.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true); expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("desktop shows top navigation and chart controls", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 }); await mockApi(page); await page.goto("/charts");
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible(); await expect(page.getByRole("navigation", { name: "移动导航" })).toBeHidden(); await expect(page.getByLabel("图表开始日期")).toBeVisible(); await expect(page.getByLabel("收入分类1")).toBeChecked(); await expect(page.getByText("每日营业额")).toBeVisible();
});
