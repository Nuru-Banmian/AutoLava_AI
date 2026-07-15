import { expect, test, type Page } from "@playwright/test";

type Role = "admin" | "user";

const categories = Array.from({ length: 8 }, (_, index) => ({ id: index + 1, name: `收入分类${index + 1}`, include_in_total: index < 2, is_active: true, sort_order: index + 1 }));
const emptyDb = { items: [], categories, sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 50 };

async function mockApi(page: Page, options: { authenticated?: boolean; role?: Role; storeName?: string } = {}) {
  let authenticated = options.authenticated ?? true;
  const role = options.role ?? "user";
  const user = { id: 1, username: role === "admin" ? "administrator" : "operator", role };
  const storeName = options.storeName ?? "Berlin";

  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });

    if (path === "/api/auth/me") return authenticated ? json(user) : json({ detail: "Authentication required" }, 401);
    if (path === "/api/auth/login" && request.method() === "POST") { authenticated = true; return json(user); }
    if (path === "/api/stores/accessible") return json([{ id: 1, name: storeName, timezone: "Europe/Berlin" }]);
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

async function expectNoHorizontalScroll(page: Page) {
  await expect.poll(() => page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
    viewport: window.innerWidth,
  }))).toEqual({ document: 320, body: 320, viewport: 320 });
}

async function loginAs(page: Page, role: Role, options: { storeName?: string } = {}) {
  await mockApi(page, { authenticated: false, role, storeName: options.storeName });
  await page.goto("/login");
  await page.getByLabel("用户名").fill(role === "admin" ? "administrator" : "operator");
  await page.getByLabel("密码", { exact: true }).fill("password-123");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "登录" })).toBeHidden();
}

test("mobile login and shell stay inside a 320px viewport", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await mockApi(page, { authenticated: false });
  await page.goto("/login");

  await expect(page.getByRole("heading", { name: "登录" })).toBeVisible();
  await expectNoHorizontalScroll(page);

  await page.getByLabel("用户名").fill("operator");
  await page.getByLabel("密码", { exact: true }).fill("password-123");
  await page.getByRole("button", { name: "登录" }).click();

  const mobileNavigation = page.getByRole("navigation", { name: "移动导航" });
  await expect(mobileNavigation.getByRole("link")).toHaveCount(4);
  await expect(mobileNavigation.getByRole("link")).toHaveText(["首页", "记账", "记录", "更多"]);
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeHidden();
  await expectNoHorizontalScroll(page);
});

test("mobile More keeps maximum-length store content reachable above navigation", async ({ page }) => {
  const storeName = "超".repeat(120);
  await page.setViewportSize({ width: 320, height: 320 });
  await loginAs(page, "user", { storeName });

  await page.getByRole("navigation", { name: "移动导航" }).getByRole("link", { name: "更多" }).click();
  const more = page.getByRole("navigation", { name: "更多功能" });
  await expect(more.getByRole("option", { name: storeName })).toBeAttached();
  await expect(more.getByRole("link", { name: "经营分析" })).toBeVisible();
  await expect(more.getByRole("link", { name: "修改密码" })).toBeVisible();
  await expect(page.getByRole("link", { name: "管理中心" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "系统状态" })).toHaveCount(0);
  await expectNoHorizontalScroll(page);

  const lastAction = page.getByRole("button", { name: "退出登录" });
  const bottomNavigation = page.getByRole("navigation", { name: "移动导航" });
  await page.mouse.wheel(0, 1_000);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  const [actionBox, navigationBox] = await Promise.all([lastAction.boundingBox(), bottomNavigation.boundingBox()]);
  expect(actionBox, "退出登录按钮应有真实浏览器布局框").not.toBeNull();
  expect(navigationBox, "移动底栏应有真实浏览器布局框").not.toBeNull();
  expect(actionBox!.y + actionBox!.height).toBeLessThanOrEqual(navigationBox!.y);
});

test("database owns horizontal table scrolling on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await mockApi(page);
  await page.goto("/database");

  const scroller = page.getByTestId("record-table-scroll");
  await expect(scroller).toBeVisible();
  expect(await scroller.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true);
  await expectNoHorizontalScroll(page);
});

test("desktop sidebar preserves exact role navigation and chart controls", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockApi(page, { role: "admin" });
  await page.goto("/charts");

  const desktopNavigation = page.getByRole("navigation", { name: "主导航" });
  await expect(desktopNavigation).toBeVisible();
  await expect(desktopNavigation.getByRole("link")).toHaveText(["首页", "每日记账", "历史记录", "经营分析", "管理中心"]);
  await expect(page.getByRole("navigation", { name: "移动导航" })).toBeHidden();
  await expect(page.getByLabel("图表开始日期")).toBeVisible();
  await expect(page.getByLabel("收入分类1")).toBeChecked();
  await expect(page.getByText("每日营业额")).toBeVisible();
});
