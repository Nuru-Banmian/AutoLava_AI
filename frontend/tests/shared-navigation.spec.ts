import { expect, test } from "@playwright/test";

const longName = "用于检查当前业务门店的特别特别特别特别特别长的门店名称";

for (const width of [320, 390, 768, 1024, 1280]) {
  test(`shared navigation keeps the selected store and account tasks usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, (route) => {
      const path = new URL(route.request().url()).pathname;
      const body = path === "/api/auth/me"
        ? { id: 1, username: "test-operator", role: "user", is_owner: false }
        : path === "/api/stores/accessible"
          ? [
              { id: 1, name: longName, timezone: "Europe/Rome", company_settlement_enabled: true, wash_count_enabled: true },
              { id: 2, name: "无公司结算的测试门店", timezone: "Europe/Rome", company_settlement_enabled: false, wash_count_enabled: true },
            ]
          : { detail: "Unexpected test request" };
      return route.fulfill({ status: path === "/api/auth/me" || path === "/api/stores/accessible" ? 200 : 500, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto("/more");
    const picker = page.getByTestId(width < 768 ? "mobile-store-picker" : "desktop-store-picker");
    const store = picker.getByRole("combobox", { name: "门店" });
    await store.selectOption("1");
    await expect(picker.getByText(longName, { exact: false }).last()).toBeVisible();
    await expect(page.getByRole("navigation", { name: "更多功能" }).getByRole("link", { name: "公司结算" })).toBeVisible();
    await expect(page.getByRole("link", { name: "管理中心", exact: true })).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    expect((await store.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    expect(await store.evaluate((node) => parseFloat(getComputedStyle(node).fontSize))).toBeGreaterThanOrEqual(16);
    if (width < 768) {
      const navigation = page.getByRole("navigation", { name: "移动导航" });
      await expect(navigation.getByRole("link")).toHaveText(["首页", "记账", "记录", "更多"]);
    }
    await store.selectOption("2");
    await expect(page.getByRole("link", { name: "公司结算", exact: true })).toHaveCount(0);
    await page.getByRole("navigation", { name: "更多功能" }).getByRole("link", { name: "修改密码" }).click();
    await expect(page.getByRole("heading", { name: "修改密码" })).toBeVisible();
    if (width < 768) await expect(page.getByRole("navigation", { name: "移动导航" }).getByRole("link", { name: "更多" })).toHaveAttribute("aria-current", "page");
    await page.getByLabel("当前密码").fill("test-password");
    await page.getByLabel("新密码", { exact: true }).fill("new-test-password");
    await page.getByLabel("确认新密码").fill("different-password");
    await page.getByRole("button", { name: "更新密码" }).click();
    await expect(page.getByRole("alert")).toHaveText("两次输入的新密码不一致");
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
