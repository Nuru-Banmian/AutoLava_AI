import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Locator } from "@playwright/test";

test.skip(!process.env.AUTOLAVA_GROUPS_MANIFEST, "Use scripts/verify-issue-228-live.py");

async function rect(locator: Locator) {
  const value = await locator.boundingBox();
  if (!value) throw new Error("Expected visible browser geometry");
  return value;
}

for (const width of [390, 1280]) {
  test(`${width}px: home bookkeeping save, record paging, analysis detail edit and return`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/login");
    await page.getByLabel("用户名").fill(process.env.AUTOLAVA_LIVE_USERNAME!);
    await page.getByLabel("密码", { exact: true }).fill(process.env.AUTOLAVA_LIVE_PASSWORD!);
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await expect(page.getByRole("heading", { name: "首页", exact: true })).toBeVisible();
    const created = await page.request.post("/api/admin/stores", { data: {
      name: `T6 save and return ${width}`, address: "Synthetic address",
      latitude: "45", longitude: "9", timezone: "Europe/Rome",
    } });
    expect(created.status()).toBe(201);
    const storeId = (await created.json()).id;
    await page.reload();
    await page.getByTestId(width < 768 ? "mobile-store-picker" : "desktop-store-picker")
      .getByLabel("门店").selectOption(String(storeId));
    await page.getByRole("link", { name: "立即记账", exact: true }).click();
    await page.getByLabel("当日营业额", { exact: true }).fill("150");
    await page.getByRole("button", { name: "保存今日记录", exact: true }).click();
    await expect(page.getByRole("button", { name: "保存修改", exact: true })).toBeVisible();
    await page.goto("/ledger?date=2026-07-01");
    await page.getByLabel("当日营业额", { exact: true }).fill("100");
    await page.getByRole("button", { name: "补记历史记录", exact: true }).click();
    await expect(page.getByRole("button", { name: "保存修改", exact: true })).toBeVisible();
    await page.goto("/database");
    await page.getByLabel("月份", { exact: true }).fill("2026-07");
    await page.getByRole("navigation", { name: "记录分页" }).getByRole("button", { name: "下一页" }).click();
    await expect(page.getByText("第 2 / 3 页", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "经营分析", exact: true }).click();
    const income = page.getByRole("region", { name: "收入构成", exact: true });
    await expect(income.locator("footer")).toContainText("€100");
    await expect(income.getByLabel("未分类营业额 占比 100.0%", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "2026-07-01 营业 €100", exact: true }).click();
    const detail = width < 1024 ? page.getByRole("region", { name: "2026-07-01 营业记录详情", exact: true }) : page.getByRole("complementary").filter({ has: page.getByRole("heading", { name: "2026年7月1日 星期三", exact: true }) });
    await detail.getByRole("link", { name: "修改这天记录", exact: true }).click();
    await page.getByLabel("当日营业额", { exact: true }).fill("175");
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await expect(page).toHaveURL(/\/database(?:\?date=2026-07-01)?$/);
    await expect(detail).toContainText("€175");
    if (width < 768) await detail.getByRole("button", { name: "返回记录", exact: true }).click();
    await expect(page.getByText("第 3 / 3 页", { exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "记录筛选" }).getByLabel("月份", { exact: true })).toHaveValue("2026-07");
    await page.getByRole("button", { name: "经营分析", exact: true }).click();
    await expect(income.locator("footer")).toContainText("€175");
  });
}

for (const width of [320, 390, 768, 1024, 1280]) {
  test(`${width}px: complete income, unequal cards and calendar return on real services`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const manifest = JSON.parse(readFileSync(process.env.AUTOLAVA_GROUPS_MANIFEST!, "utf8"));
    if (!manifest.composition_store) test.skip(true, "T6 fixture required");
    await page.goto("/login");
    await page.getByLabel("用户名").fill(process.env.AUTOLAVA_LIVE_USERNAME!);
    await page.getByLabel("密码", { exact: true }).fill(process.env.AUTOLAVA_LIVE_PASSWORD!);
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await expect(page.getByRole("heading", { name: "首页", exact: true })).toBeVisible();
    await page.getByTestId(width < 768 ? "mobile-store-picker" : "desktop-store-picker")
      .getByLabel("门店").selectOption(String(manifest.composition_store));
    await page.goto("/database");
    await page.getByLabel("月份", { exact: true }).fill("2026-07");
    await page.getByRole("button", { name: "经营分析", exact: true }).click();
    const summary = page.getByRole("region", { name: "月度收入汇总" });
    await expect(summary).toContainText("已确认公司结算收入");
    await expect(summary).toContainText("€999.900.545");
    const composition = page.getByRole("region", { name: "收入构成", exact: true });
    await expect(composition).toContainText("未分类营业额");
    await expect(composition).toContainText("公司结算");
    await expect(composition.locator("footer")).toContainText("€999.900.545");
    await expect(composition.getByLabel("未分类营业额 占比 0.0%", { exact: true })).toBeVisible();
    await expect(composition.getByLabel("公司结算 占比 0.0%", { exact: true })).toBeVisible();
    await expect(composition.getByRole("region", { name: "其他数据" })).toContainText("€900");
    await expect(composition.getByRole("region", { name: "其他数据" }).getByText(/%/)).toHaveCount(0);
    await composition.getByRole("button", { name: /^展开收入分类/ }).click();
    await expect(composition.getByText("收入分类13超长名称验证手机金额和比例完整可读", { exact: true })).toBeVisible();
    const calendar = page.getByRole("region", { name: "营业日历", exact: true });
    const left = await rect(composition), right = await rect(calendar);
    if (width >= 1024) {
      expect(Math.abs(left.y - right.y)).toBeLessThanOrEqual(1);
      expect(Math.abs(left.height - right.height)).toBeLessThanOrEqual(1);
      expect(Math.abs((await rect(composition.locator("header"))).y - (await rect(calendar.locator("header"))).y)).toBeLessThanOrEqual(1);
      expect(Math.abs((await rect(composition.locator(":scope > div"))).y - (await rect(calendar.locator(":scope > div"))).y)).toBeLessThanOrEqual(1);
      expect(Math.abs((await rect(composition.locator("footer"))).y - (await rect(calendar.locator("footer"))).y)).toBeLessThanOrEqual(1);
    } else {
      expect(right.y).toBeGreaterThan(left.y + left.height);
      expect(left.y + left.height - (await rect(composition.locator("footer"))).y).toBeLessThan(120);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await composition.locator("..").screenshot({ path: join(process.env.AUTOLAVA_GROUPS_ARTIFACTS!, `composition-${width}.png`), animations: "disabled" });
    await calendar.getByRole("button", { name: "2026-07-01 营业 €100", exact: true }).click();
    const detail = width < 1024 ? page.getByRole("region", { name: "2026-07-01 营业记录详情", exact: true }) : page.getByRole("complementary").filter({ has: page.getByRole("heading", { name: "2026年7月1日 星期三", exact: true }) });
    await expect(detail).toBeVisible();
    if (width < 1024) {
      await detail.getByRole("button", { name: "返回记录", exact: true }).click();
      await expect(page.getByRole("button", { name: "经营分析", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "2026年7月1日 星期三，营业，€100", exact: true })).toBeFocused();
    }
  });
}
