import { expect, test, type Page } from "@playwright/test";

async function mockAgentApi(page: Page) {
  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (value: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(value),
    });

    if (path === "/api/auth/me") {
      return json({ id: 1, username: "administrator", role: "admin", is_owner: false });
    }
    if (path === "/api/stores/accessible") {
      return json([{
        id: 1,
        name: "测试门店",
        timezone: "Europe/Rome",
        wash_count_enabled: true,
        company_settlement_enabled: false,
      }]);
    }
    if (path === "/api/agent/stores/1/conversation" && request.method() === "GET") {
      return json({ messages: [] });
    }
    if (path === "/api/agent/stores/1/messages" && request.method() === "POST") {
      return json({ message: { role: "assistant", content: "您好" } });
    }
    return json({ detail: `unmocked ${request.method()} ${path}` }, 500);
  });
}

test("chat bubbles fit short messages instead of filling the conversation width", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockAgentApi(page);
  await page.goto("/agent");

  await page.getByRole("textbox", { name: "消息" }).fill("你好");
  await page.getByRole("button", { name: "发送" }).click();

  const messageLog = page.getByRole("log", { name: "对话消息" });
  const userBubble = page.getByText("你好", { exact: true }).locator("..");
  const assistantBubble = page.getByText("您好", { exact: true }).locator("..");
  await expect(assistantBubble).toBeVisible();

  const [logBox, userBox, assistantBox] = await Promise.all([
    messageLog.boundingBox(),
    userBubble.boundingBox(),
    assistantBubble.boundingBox(),
  ]);
  expect(logBox).not.toBeNull();
  expect(userBox).not.toBeNull();
  expect(assistantBox).not.toBeNull();
  expect(userBox!.width).toBeLessThan(logBox!.width / 2);
  expect(assistantBox!.width).toBeLessThan(logBox!.width / 2);
  expect(Math.abs(userBox!.x + userBox!.width - (logBox!.x + logBox!.width - 16))).toBeLessThanOrEqual(1);
  expect(Math.abs(assistantBox!.x - (logBox!.x + 16))).toBeLessThanOrEqual(1);

  await page.setViewportSize({ width: 320, height: 700 });
  const longMessage = "https://example.com/" + "very-long-unbroken-message".repeat(20);
  await page.getByRole("textbox", { name: "消息" }).fill(longMessage);
  await page.getByRole("button", { name: "发送" }).click();

  const mobileLogBox = await messageLog.boundingBox();
  const longBubble = page.getByText(longMessage, { exact: true }).locator("..");
  const longBubbleBox = await longBubble.boundingBox();
  expect(mobileLogBox).not.toBeNull();
  expect(longBubbleBox).not.toBeNull();
  expect(longBubbleBox!.width).toBeLessThanOrEqual((mobileLogBox!.width - 32) * 0.85 + 1);
  await expect.poll(() => longBubble.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320);
});
