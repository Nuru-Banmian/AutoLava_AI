import { expect, test } from "@playwright/test";
test.use({ hasTouch: true });

for (const width of [1280, 390]) {
  test(`saved chat trend through real HTTP/SSE at ${width}px`, async ({ page, context }) => {
    await page.setViewportSize({ width, height: 900 });
    // Forward API traffic to this ticket's isolated migrated database, never the business server.
    await page.route("**/api/**", async (route) => {
      if (!new URL(route.request().url()).pathname.startsWith("/api/")) return route.continue();
      const response = await context.request.fetch(route.request().url().replace("127.0.0.1:4173", "127.0.0.1:8066"), {
        method: route.request().method(), headers: route.request().headers(), data: route.request().postData() ?? undefined,
      });
      await route.fulfill({ response });
    });
    await page.goto("/login");
    await page.getByLabel("用户名").fill("user-1");
    await page.getByLabel("密码", { exact: true }).fill("Password123");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await expect(page.getByRole("heading", { name: "登录", exact: true })).toHaveCount(0);
    await page.goto("/ai");
    await page.getByRole("combobox", { name: "门店", exact: true }).selectOption("1");
    await expect(page.getByRole("button", { name: "重置对话" })).toBeEnabled();
    await page.getByRole("button", { name: "重置对话" }).click();
    await expect(page.getByRole("button", { name: "重置对话" })).toBeEnabled();
    await page.getByLabel("发送消息").fill("画四天营业额趋势");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    const chart = page.getByRole("figure", { name: "逐日营业额" });
    await expect(chart).toBeVisible();
    const data = chart.getByRole("status", { name: "图表数据" });
    await chart.getByLabel("逐日营业额查看日期").selectOption("1");
    await expect(data).toContainText("：0 EUR");
    await chart.getByLabel("逐日营业额查看日期").selectOption("2");
    await expect(data).toContainText("未统计");
    await expect(data).toContainText("未知");
    await chart.getByLabel("逐日营业额查看日期").selectOption("3");
    await expect(data).toContainText("未录入");
    const dot = chart.locator(".recharts-line-dot").first();
    if (width > 768) await dot.hover();
    else await dot.tap();
    await expect(data).toContainText("：19 EUR");
    await expect(chart.locator(".recharts-line-dot")).toHaveCount(2);
    await expect(page.getByRole("button", { name: /下载/ })).toHaveCount(0);
    await page.reload();
    await expect(chart).toHaveCount(1);
    await expect(chart).toBeVisible();
    await chart.getByLabel("逐日营业额查看日期").selectOption("0");
    await expect(data).toContainText("：19 EUR");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: `output/playwright/issue266-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "重置对话" }).click();
    await expect(chart).toHaveCount(0);
  });
}
