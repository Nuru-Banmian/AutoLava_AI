import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

test.skip(!process.env.AUTOLAVA_GROUPS_MANIFEST, "Use scripts/verify-issue-228-live.py");

async function login(page: Page, username = process.env.AUTOLAVA_LIVE_USERNAME!, password = process.env.AUTOLAVA_LIVE_PASSWORD!) {
  await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "首页", exact: true })).toBeVisible();
}

for (const width of [390, 1280]) {
  test(`${width}px: real records and charts survive injected transport failures and rapid scope changes`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const manifest = JSON.parse(readFileSync(process.env.AUTOLAVA_GROUPS_MANIFEST!, "utf8"));
    await login(page);
    const storeId = manifest.composition_store;
    const picker = page.getByTestId(width < 768 ? "mobile-store-picker" : "desktop-store-picker").getByLabel("门店");
    await picker.selectOption(String(storeId));
    let failRecords = true, failCharts = false;
    let attempts = 0;
    await page.route(`**/api/database/${storeId}/records?**`, async (route) => {
      attempts++;
      if (failRecords) await route.fulfill({ status: 503, body: "{}", contentType: "application/json" });
      else await route.continue();
    });
    await page.route(`**/api/charts/${storeId}?**`, async (route) => {
      if (failCharts) await route.fulfill({ status: 503, body: "{}", contentType: "application/json" });
      else await route.continue();
    });
    await page.goto("/database");
    await expect(page.getByRole("button", { name: "重试", exact: true })).toBeVisible({ timeout: 20000 });
    expect(attempts).toBeGreaterThanOrEqual(4);
    await expect(page.getByText("未录入", { exact: true })).toHaveCount(0);
    failRecords = false;
    await page.getByRole("button", { name: "重试", exact: true }).click();
    const month = page.getByRole("region", { name: "记录筛选" }).getByLabel("月份", { exact: true });
    await month.fill("2026-07");
    await page.getByRole("button", { name: "经营分析", exact: true }).click();
    const income = page.getByRole("region", { name: "收入构成", exact: true });
    await expect(income.locator("footer")).toContainText("€999.900.545");
    await month.fill("2026-06");
    await expect(income).toContainText("暂无收入构成");
    failCharts = true;
    await month.fill("2026-07");
    await expect(page.getByText("刷新经营分析失败，当前显示上次取得的数据。", { exact: true })).toBeVisible({ timeout: 20000 });
    await expect(income.locator("footer")).toContainText("€999.900.545");
    failCharts = false;
    await page.getByRole("button", { name: "重试经营分析", exact: true }).click();
    await expect(page.getByText("刷新经营分析失败，当前显示上次取得的数据。", { exact: true })).toHaveCount(0);
    await month.fill("2026-06");
    await month.fill("2026-07");
    await picker.selectOption(String(manifest.scopes[2].store_id));
    await month.fill("2026-06");
    await expect(page.getByRole("listitem", { name: "未记录：€203，2 天经营日样本", exact: true })).toBeVisible();
    await expect(income.locator("footer")).not.toContainText("€999.900.545");
  });
}

test("real draft guards, export, administrator draft and backup permissions", async ({ page, browser, baseURL }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await login(page);
  const manifest = JSON.parse(readFileSync(process.env.AUTOLAVA_GROUPS_MANIFEST!, "utf8"));
  await page.getByTestId("desktop-store-picker").getByLabel("门店").selectOption(String(manifest.scopes[0].store_id));
  await page.goto("/ledger?date=2026-06-01");
  await page.getByLabel("当日营业额", { exact: true }).fill("999");
  await page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "营业记录", exact: true }).click();
  const guard = page.getByRole("alertdialog", { name: "放弃未保存的修改？" });
  await expect(guard).toBeVisible();
  await guard.getByRole("button", { name: "继续编辑" }).click();
  await expect(page.getByLabel("当日营业额", { exact: true })).toHaveValue("999");
  await page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "营业记录", exact: true }).click();
  await guard.getByRole("button", { name: "放弃修改" }).click();
  await page.getByLabel("月份", { exact: true }).fill("2026-06");
  const exportDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出当前范围", exact: true }).click();
  expect((await exportDownload).suggestedFilename()).toMatch(/\.xlsx$/);
  await page.goto("/admin");
  await page.getByRole("button", { name: "新建门店", exact: true }).click();
  await page.getByLabel("门店名称", { exact: true }).fill("T6 unsaved synthetic draft");
  await page.getByRole("tab", { name: "系统状态", exact: true }).click();
  await expect(guard).toBeVisible();
  await guard.getByRole("button", { name: "继续编辑" }).click();
  await expect(page.getByLabel("门店名称", { exact: true })).toHaveValue("T6 unsaved synthetic draft");
  await page.getByRole("tab", { name: "系统状态", exact: true }).click();
  await guard.getByRole("button", { name: "放弃修改" }).click();
  await page.getByRole("button", { name: "下载数据库备份", exact: true }).click();
  const backup = page.getByRole("alertdialog", { name: "下载完整数据库备份？" });
  await backup.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("button", { name: "下载数据库备份", exact: true }).click();
  const backupDownload = page.waitForEvent("download");
  await backup.getByRole("button", { name: "确认并下载", exact: true }).click();
  expect((await backupDownload).suggestedFilename()).toMatch(/\.sqlite3$/);
  for (const role of ["user", "admin"]) {
    const username = `t6-${role}`, password = "SyntheticPass1";
    const created = await page.request.post("/api/admin/users", { data: { username, password, role, store_ids: [manifest.scopes[0].store_id] } });
    expect(created.status()).toBe(201);
    const context = await browser.newContext({ baseURL });
    try {
      const restricted = await context.newPage();
      await login(restricted, username, password);
      await restricted.goto("/admin?tab=status");
      await expect(restricted.getByRole("button", { name: "下载数据库备份", exact: true })).toHaveCount(0);
      if (role === "user") await expect(restricted.getByRole("tab", { name: "系统状态", exact: true })).toHaveCount(0);
    } finally { await context.close(); }
  }
});
