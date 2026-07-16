import { expect, test, type Page } from "@playwright/test";

type Capture = {
  incomePublish?: unknown;
  createdUser?: unknown;
  createdStore?: unknown;
};

const store = { id: 1, name: "Roma", address: "Roma, Italia", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true };

async function mockAdminApi(page: Page, capture: Capture) {
  let authenticated = false;
  let users: unknown[] = [];
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: {
        getCurrentPosition(success: PositionCallback) {
          success({ coords: { latitude: 41.9, longitude: 12.5 } } as GeolocationPosition);
        },
      },
    });
  });
  await page.route("https://tile.openstreetmap.org/**", (route) => route.fulfill({ status: 204, body: "" }));
  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });

    if (path === "/api/auth/me") return authenticated ? json({ id: 1, username: "administrator", role: "admin" }) : json({ detail: "Authentication required" }, 401);
    if (path === "/api/auth/login" && request.method() === "POST") { authenticated = true; return json({ id: 1, username: "administrator", role: "admin" }); }
    if (path === "/api/stores/accessible") return json([store]);
    if (path === "/api/admin/stores" && request.method() === "GET") return json([store]);
    if (path === "/api/admin/users" && request.method() === "GET") return json(users);
    if (path === "/api/admin/users" && request.method() === "POST") {
      capture.createdUser = request.postDataJSON();
      users = [{ id: 2, ...(capture.createdUser as object), is_active: true, store_ids: [] }];
      return json(users[0], 201);
    }
    if (path === "/api/admin/alerts") return json([]);
    if (path === "/api/admin/task-logs") return json([{ id: 1, store_id: 1, task_type: "weather", status: "success", message: null, retry_count: 0, started_at: "2026-07-16T08:00:00Z", finished_at: "2026-07-16T08:05:00Z", created_at: "2026-07-16T08:00:00Z" }]);
    if (path === "/api/dashboard/1") return json([{ card_type: "today", state: "recorded", revenue: "100.00", weather: "晴", weekday: null, temperature_max: null, temperature_min: null, precipitation: null, hint: null, generated_at: "2026-07-16T08:30:00Z" }]);
    if (path === "/api/income-config/1/current") return json({ store_id: 1, version_id: 1, version: 1, enabled: true, formula: "营业额 = 现金", created_at: "2026-07-16T08:00:00Z", items: [{ id: 1, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 0 }] });
    if (path === "/api/admin/income-categories") return json([{ id: 1, store_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 0, archived_at: null }]);
    if (path === "/api/admin/stores/1/income-config" && request.method() === "PUT") {
      capture.incomePublish = request.postDataJSON();
      return json({ store_id: 1, version_id: 2, version: 2, enabled: true, formula: "营业额 = 现金 + 其他", created_at: "2026-07-16T09:00:00Z", items: [
        { id: 1, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 0 },
        { id: 2, category_id: 2, name: "其他", include_in_total: true, is_active: true, sort_order: 1 },
      ] });
    }
    if (path === "/api/admin/stores/geocode") return json([{ name: "Milano", country: "Italia", latitude: 45.4642, longitude: 9.19, timezone: "Europe/Rome" }]);
    if (path === "/api/admin/stores/timezone") return json({ timezone: "Europe/Rome" });
    if (path === "/api/admin/stores" && request.method() === "POST") {
      capture.createdStore = request.postDataJSON();
      return json({ id: 2, ...(capture.createdStore as object), is_active: true }, 201);
    }
    return json({ detail: `unmocked ${request.method()} ${path}` }, 500);
  });
}

test("admin configures income, user, and mapped store without coordinate fields", async ({ page }) => {
  const capture: Capture = {};
  await mockAdminApi(page, capture);
  await page.goto("/login");
  await page.getByLabel("用户名").fill("administrator");
  await page.getByLabel("密码", { exact: true }).fill("password-123");
  await page.getByRole("button", { name: "登录" }).click();
  await page.goto("/admin");

  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveText(["收入项目", "用户与权限", "门店设置", "系统状态"]);
  await expect(page.getByRole("tab", { name: "收入项目" })).toHaveAttribute("aria-selected", "true");
  await page.getByLabel("收入项目门店").selectOption("1");
  await page.getByLabel("新收入项目名称").fill("其他");
  await page.getByRole("button", { name: "添加收入项目" }).click();
  await page.getByRole("button", { name: "保存并发布" }).click();
  await expect.poll(() => capture.incomePublish).toMatchObject({ enabled: true, items: [{ name: "现金" }, { name: "其他" }] });

  await page.getByRole("tab", { name: "用户与权限" }).click();
  await page.getByLabel("新用户名").fill("operator");
  await page.getByLabel("初始密码").fill("operator-123");
  await page.getByRole("button", { name: "添加用户" }).click();
  await expect.poll(() => capture.createdUser).toEqual({ username: "operator", password: "operator-123", role: "user" });

  await page.getByRole("tab", { name: "门店设置" }).click();
  await expect(page.getByLabel("纬度")).toHaveCount(0);
  await expect(page.getByLabel("经度")).toHaveCount(0);
  await page.getByRole("button", { name: "新建门店" }).click();
  await page.getByLabel("门店名称", { exact: true }).fill("Milano");
  await page.getByRole("button", { name: "打开地图选择" }).click();
  await page.getByLabel("搜索城市、区域或地点").fill("Milano");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await page.getByRole("button", { name: "Milano, Italia" }).click();
  await page.getByRole("button", { name: "确认位置" }).click();
  await page.getByRole("button", { name: "添加门店" }).click();
  await expect.poll(() => capture.createdStore).toEqual({ name: "Milano", address: "Milano, Italia", latitude: 45.4642, longitude: 9.19, timezone: "Europe/Rome" });
});
