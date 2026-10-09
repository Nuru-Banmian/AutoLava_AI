import { expect, test } from "@playwright/test";
test.use({ hasTouch: true });

for (const width of [1280, 390]) {
  for (const scenario of ["构成", "比较", "排名", "长趋势", "超量长趋势"]) {
    test(`${scenario} through real query/HTTP/SSE at ${width}px`, async ({ page, context }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.route("**/api/**", async (route) => {
        if (!new URL(route.request().url()).pathname.startsWith("/api/")) return route.continue();
        const response = await context.request.fetch(route.request().url().replace("127.0.0.1:4173", "127.0.0.1:8067"), {
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
      await page.getByLabel("发送消息").fill(`画${scenario}`);
      await page.getByRole("button", { name: "发送", exact: true }).click();
      const figures = page.getByRole("figure");
      const expected = scenario === "比较" ? 2 : scenario === "超量长趋势" ? 6 : scenario === "长趋势" ? 3 : 1;
      await expect(figures).toHaveCount(expected);
      const first = figures.first();
      await expect(first).toBeVisible();
      const data = first.getByRole("status", { name: "图表数据" });
      if (scenario === "构成" || scenario === "排名" || scenario === "比较") {
        const bar = first.locator(".recharts-bar-rectangle path").first();
        if (width > 768) await bar.hover(); else await bar.tap();
        await expect(data).toContainText(scenario === "构成" ? "25 EUR" : scenario === "排名" ? "100 EUR" : "199 EUR");
        if (scenario === "构成") {
          await first.getByRole("combobox").selectOption("1");
          await expect(data).toContainText("刷卡：0 EUR");
          await first.getByRole("combobox").selectOption("2");
          await expect(data).toContainText("未知");
        }
        if (scenario === "比较") {
          await expect(figures.nth(1)).toContainText("辆");
          await expect(figures.nth(1)).toContainText("2026-07-01 至 2026-08-31");
        }
      } else {
        await expect(first).toContainText("第 1/3 段");
        await expect(figures.nth(2)).toContainText("第 3/3 段");
        await figures.nth(2).getByRole("combobox").selectOption("183");
        await expect(figures.nth(2).getByRole("status", { name: "图表数据" })).toContainText("99 EUR");
        if (scenario.startsWith("超量")) await expect(page.getByText(/图表请求未生成/)).toBeVisible();
      }
      await expect(page.getByRole("button", { name: /下载/ })).toHaveCount(0);
      await page.reload();
      await expect(figures).toHaveCount(expected);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
      await page.screenshot({ path: `output/playwright/issue267-${scenario}-${width}.png`, fullPage: true });
    });
  }
}
