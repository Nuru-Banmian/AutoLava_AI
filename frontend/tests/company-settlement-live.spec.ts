import { expect, test } from "@playwright/test";

test.skip(!process.env.AUTOLAVA_LIVE_BROWSER, "Run only against an isolated migrated SQLite database");

test("real backend browser creates, confirms, and revokes a settlement record", async ({ page }) => {
  const username = process.env.AUTOLAVA_LIVE_USERNAME;
  const password = process.env.AUTOLAVA_LIVE_PASSWORD;
  if (!username || !password) throw new Error("Isolated browser credentials are required");

  await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "首页" })).toBeVisible();

  const createdStore = await page.request.post("/api/admin/stores", {
    data: {
      name: "Issue 194 Browser Store",
      address: "Temporary test address",
      latitude: "45.0",
      longitude: "9.0",
      timezone: "Europe/Rome",
    },
  });
  expect(createdStore.status()).toBe(201);
  const storeId = (await createdStore.json() as { id: number }).id;
  const enabled = await page.request.patch(`/api/admin/stores/${storeId}`, {
    data: { company_settlement_enabled: true },
  });
  expect(enabled.ok()).toBe(true);

  await page.goto("/settlements");
  await expect(page.getByRole("heading", { name: "公司结算" })).toBeVisible();
  await page.getByRole("button", { name: "结算公司管理" }).click();
  await page.getByRole("textbox", { name: "新结算公司名称" }).fill("Issue 194 Fleet");
  await page.getByRole("button", { name: "新增结算公司" }).click();
  await expect(page.getByRole("button", { name: "Issue 194 Fleet更多操作" })).toBeVisible();

  await page.getByRole("combobox", { name: "结算公司", exact: true }).selectOption({ label: "Issue 194 Fleet" });
  await page.getByRole("spinbutton", { name: "金额（整数欧元）" }).fill("120");
  await page.getByRole("button", { name: "登记待到账记录" }).click();
  await expect(page.getByRole("button", { name: "确认Issue 194 Fleet开票记录到账" })).toBeVisible();
  await page.getByRole("button", { name: "确认Issue 194 Fleet开票记录到账" }).click();
  await page.getByRole("alertdialog", { name: "确认整笔到账？" }).getByRole("button", { name: "确认到账" }).click();
  await expect(page.getByRole("status")).toContainText("开票记录已确认到账");

  const month = await page.getByLabel("开票月份").inputValue();
  const confirmed = await page.request.get(`/api/settlements/${storeId}/months/${month}`);
  expect(confirmed.ok()).toBe(true);
  const confirmedRecord = (await confirmed.json() as { records: { status: string; amount: number }[] }).records[0];
  expect(confirmedRecord).toMatchObject({ status: "confirmed", amount: 120 });

  await page.getByRole("button", { name: "Issue 194 Fleet开票记录更多操作" }).click();
  await page.getByRole("menuitem", { name: "撤销Issue 194 Fleet开票记录到账确认" }).click();
  await page.getByRole("alertdialog", { name: "撤销到账确认？" }).getByRole("button", { name: "确认撤销到账确认" }).click();
  await expect(page.getByRole("status")).toContainText("已撤销开票记录到账确认");
  const revoked = await page.request.get(`/api/settlements/${storeId}/months/${month}`);
  expect(revoked.ok()).toBe(true);
  expect((await revoked.json() as { records: { status: string }[] }).records[0].status).toBe("pending");
});
