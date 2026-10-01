import { expect, test } from "@playwright/test";

const recordDate = "2026-07-15";

test("release Web uses a Secure Cookie to save and reread a ledger entry", async ({ page }) => {
  const phase = process.env.RELEASE_PHASE ?? "before";
  const username = process.env.AUTOLAVA_BOOTSTRAP_USERNAME;
  const password = process.env.AUTOLAVA_BOOTSTRAP_PASSWORD;
  if (!username || !password) throw new Error("Release credentials are required");

  await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "登录" })).toHaveCount(0);

  const cookie = (await page.context().cookies()).find((item) => item.name === "access_token");
  expect(cookie?.secure).toBe(true);
  const me = await page.request.get("/api/auth/me");
  expect(me.ok()).toBe(true);

  await page.goto(`/ledger?date=${recordDate}`);
  await expect(page.getByRole("heading", { name: "记账" })).toBeVisible();
  if (phase === "before") {
    await page.getByLabel("当日营业额").fill("150");
    await page.getByLabel("洗车数量").fill("3");
    await page.getByRole("button", { name: "补记历史记录" }).click();
    await expect(page.getByRole("status").filter({ hasText: "保存成功" })).toBeVisible();
  }
  await page.reload();
  await expect(page.getByLabel("当日营业额")).toHaveValue("150");
  await expect(page.getByLabel("洗车数量")).toHaveValue("3");

  await page.request.post("/api/auth/logout");
  expect((await page.request.get("/api/auth/me")).status()).toBe(401);
});
