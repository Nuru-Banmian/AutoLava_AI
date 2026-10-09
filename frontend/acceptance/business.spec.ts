import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

const password = "ci-acceptance-password";

async function identity(request: APIRequestContext, role: "user" | "admin") {
  const login = await request.post("/api/auth/login", { data: { username: "ci-owner", password } });
  expect(login.status()).toBe(200);
  const me = await request.get("/api/auth/me");
  expect(me.status()).toBe(200);
  const owner = await me.json();
  const createdStore = await request.post("/api/admin/stores", { data: {
    name: `浏览器验收-${randomUUID().slice(0, 8)}`, address: "Rome", latitude: "41.9", longitude: "12.5",
  } });
  expect(createdStore.status()).toBe(201);
  const store = await createdStore.json();
  const username = `browser-${randomUUID().slice(0, 8)}`;
  const createdUser = await request.post("/api/admin/users", { data: {
    username, password, role, store_ids: [store.id],
    ...(role === "user" ? { manager_id: owner.id } : {}),
  } });
  expect(createdUser.status()).toBe(201);
  return { username, storeId: store.id };
}

async function signIn(page: Page, username: string, storeId: number) {
  await page.goto("/login");
  await page.getByLabel("用户名", { exact: true }).fill(username);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  const picker = page.getByRole("combobox", { name: "门店", exact: true }).filter({ visible: true });
  await expect(picker).toBeEnabled();
  await picker.selectOption(String(storeId));
  await expect(picker).toHaveValue(String(storeId));
}

async function fitsScreen(page: Page) {
  // Wait for the meaningful page content before inspecting layout.
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
}

test("记账保存、刷新与真实零转未统计", async ({ page, request }) => {
  const { username, storeId } = await identity(request, "user");
  await signIn(page, username, storeId);
  await page.goto("/ledger?date=2025-01-02");
  await expect(page.getByRole("heading", { name: "记账", exact: true })).toBeVisible();
  await page.getByLabel("当日营业额", { exact: true }).fill("0");
  await page.getByLabel("事件", { exact: true }).fill("已清点，收入为零");
  await page.getByRole("button", { name: "补记历史记录" }).click();
  await expect(page.getByText("保存成功", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("当日营业额", { exact: true })).toHaveValue("0");
  await expect(page.getByLabel("事件", { exact: true })).toHaveValue("已清点，收入为零");
  await page.getByLabel("状态", { exact: true }).selectOption("未统计");
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.getByRole("button", { name: "确认清除并保存" }).click();
  await expect(page.getByText("保存成功", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("状态", { exact: true })).toHaveValue("未统计");
  await expect(page.getByLabel("当日营业额", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("当日营业额", { exact: true })).toBeDisabled();
  await expect(page.getByRole("note")).toContainText("营业额与洗车数量未知");
  const persisted = await page.request.get(`/api/ledger/${storeId}/2025-01-02`);
  expect(persisted.status()).toBe(200);
  expect(await persisted.json()).toMatchObject({ is_open: "未统计", daily_revenue: null, activity: "已清点，收入为零" });
  await fitsScreen(page);
});

test("AI 对话图表准确值、刷新恢复与重置", async ({ page, request }) => {
  const { username, storeId } = await identity(request, "admin");
  const config = await request.get(`/api/ledger/${storeId}/2025-01-03/form-config`);
  expect(config.status()).toBe(200);
  const created = await request.put(`/api/ledger/${storeId}/2025-01-03`, { data: {
    expected_identity: null, expected_revision: null,
    expected_config_revision: (await config.json()).config_revision,
    is_open: "营业", daily_revenue: 81,
  } });
  expect(created.status()).toBe(201);
  await signIn(page, username, storeId);
  await page.goto("/ai");
  await page.getByLabel("发送消息", { exact: true }).fill("查询2025年1月1至4日营业额并画图，另算0.1+0.2");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText("回答已完成并保存", { exact: true })).toBeVisible();
  const chart = page.getByRole("figure", { name: "验收营业额" });
  await page.locator("[data-chart-id]").scrollIntoViewIfNeeded();
  await expect(chart).toBeVisible();
  await chart.getByLabel("验收营业额查看日期").selectOption("2");
  await expect(chart.getByRole("status", { name: "图表数据" })).toContainText("81 EUR");
  await fitsScreen(page);
  await page.reload();
  await expect(page.getByText("回答已完成并保存", { exact: true })).toBeVisible();
  await page.locator("[data-chart-id]").scrollIntoViewIfNeeded();
  await chart.getByLabel("验收营业额查看日期").selectOption("0");
  await expect(chart.getByRole("status", { name: "图表数据" })).toContainText("未知");
  await page.getByRole("button", { name: "重置对话", exact: true }).click();
  await expect(page.locator('[aria-label="聊天记录"] article')).toHaveCount(0);
  await expect(chart).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel("发送消息", { exact: true })).toBeVisible();
  await expect(page.locator('[aria-label="聊天记录"] article')).toHaveCount(0);
});

test("普通用户直接进入管理员与 AI 页面仍被隔离", async ({ page, request }) => {
  const { username, storeId } = await identity(request, "user");
  await signIn(page, username, storeId);
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "用户管理", exact: true })).toHaveCount(0);
  await page.goto("/ai");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByLabel("发送消息", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "主导航", exact: true }).or(
    page.getByRole("navigation", { name: "移动导航", exact: true }),
  ).filter({ visible: true })).toBeVisible();
  await fitsScreen(page);
});
