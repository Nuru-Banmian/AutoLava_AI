import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

const backend = "http://127.0.0.1:8068";

async function seed(request: APIRequestContext) {
  const history = await (await request.get(`${backend}/api/agent/1/conversation`)).json();
  const reset = await request.post(`${backend}/api/agent/1/conversation/reset`, { data: { generation: history.generation } });
  expect(reset.ok()).toBe(true);
  const generation = (await reset.json()).generation;
  for (let index = 0; index < 12; index++) {
    const submitted = await request.post(`${backend}/api/agent/1/messages`, {
      data: { content: `画趋势 ${index + 1}`, request_id: crypto.randomUUID(), generation },
    });
    expect(submitted.status()).toBe(202);
    const id = (await submitted.json()).id;
    await expect.poll(async () => (await (await request.get(`${backend}/api/agent/1/runs/${id}`)).json()).status).toBe("completed");
  }
}

for (const width of [1280, 390]) {
  test(`long saved-chart history, loading, retry and lifecycle at ${width}px`, async ({ page, context }) => {
    await page.setViewportSize({ width, height: 900 });
    const reads: string[] = [];
    let failFirst = true;
    let hold = false;
    let release!: () => void;
    let barrier = Promise.resolve();
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith("/api/")) return route.continue();
      if (path.includes("/charts/")) {
        reads.push(path);
        if (hold) await barrier;
        if (failFirst) { failFirst = false; return route.fulfill({ status: 503, json: { detail: "暂不可用" } }); }
      }
      const response = await context.request.fetch(route.request().url().replace("127.0.0.1:4173", "127.0.0.1:8068"), {
        method: route.request().method(), headers: route.request().headers(), data: route.request().postData() ?? undefined,
      });
      try { await route.fulfill({ response }); } catch { /* navigation can cancel old requests */ }
    });
    await page.goto("/login");
    await page.getByLabel("用户名").fill("user-1");
    await page.getByLabel("密码", { exact: true }).fill("Password123");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await expect(page.getByRole("heading", { name: "登录", exact: true })).toHaveCount(0);
    await seed(context.request);
    await page.goto("/ai");
    await page.getByRole("combobox", { name: "门店", exact: true }).selectOption("1");
    const shells = page.locator("[data-chart-id]");
    await expect(shells).toHaveCount(12);
    expect(reads.length).toBeLessThan(12);
    const first = shells.first();
    await first.scrollIntoViewIfNeeded();
    const before = await first.boundingBox();
    await first.getByRole("button", { name: "重试图表" }).click();
    const firstChart = first.getByRole("figure");
    await expect(firstChart).toBeVisible();
    expect((await first.boundingBox())?.height).toBe(before?.height);
    await firstChart.getByRole("combobox").selectOption("0");
    await expect(firstChart.getByRole("status", { name: "图表数据" })).toContainText("19 EUR");
    await firstChart.getByRole("combobox").selectOption("2");
    await expect(firstChart.getByRole("status", { name: "图表数据" })).toContainText("未统计");
    const firstId = await first.getAttribute("data-chart-id");
    const firstReads = reads.filter(p => p.endsWith(`/${firstId}`)).length;
    const last = shells.last();
    await last.scrollIntoViewIfNeeded();
    await expect(last.getByRole("figure")).toBeVisible();
    await expect(first.getByRole("figure")).toHaveCount(0);
    await first.scrollIntoViewIfNeeded();
    await expect(first.getByRole("figure")).toBeVisible();
    expect(reads.filter(p => p.endsWith(`/${firstId}`)).length).toBe(firstReads);
    await page.screenshot({ path: `output/playwright/issue268-scroll-${width}.png`, fullPage: true });
    await page.reload();
    await expect(shells).toHaveCount(12);
    await first.scrollIntoViewIfNeeded();
    await expect(first.getByRole("figure")).toBeVisible();
    expect(reads.filter(p => p.endsWith(`/${firstId}`)).length).toBeGreaterThan(firstReads);
    await page.getByLabel("发送消息").fill("追问旧图");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect(page.getByText(/历史图来源：saved_chart/)).toBeVisible();
    // Hold fresh reads, switch store, and let old responses arrive afterward.
    hold = true; barrier = new Promise<void>(resolve => { release = resolve; });
    const count = reads.length;
    await page.reload();
    await expect.poll(() => reads.length).toBeGreaterThan(count);
    await page.getByRole("combobox", { name: "门店", exact: true }).selectOption("2");
    release(); hold = false;
    await expect(shells).toHaveCount(0);
    await page.getByRole("combobox", { name: "门店", exact: true }).selectOption("1");
    await expect(shells).toHaveCount(12);
    if (width < 768) await page.goto("/more");
    await page.getByRole("button", { name: "退出登录" }).click();
    await page.goto("/login");
    await page.getByLabel("用户名").fill("user-2");
    await page.getByLabel("密码", { exact: true }).fill("Password123");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.goto("/ai");
    await page.getByRole("combobox", { name: "门店", exact: true }).selectOption("1");
    await expect(shells).toHaveCount(0);
    if (width < 768) await page.goto("/more");
    await page.getByRole("button", { name: "退出登录" }).click();
    await page.goto("/login");
    await page.getByLabel("用户名").fill("user-1");
    await page.getByLabel("密码", { exact: true }).fill("Password123");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.goto("/ai");
    await page.getByRole("combobox", { name: "门店", exact: true }).selectOption("1");
    await expect(shells).toHaveCount(12);
    hold = true; barrier = new Promise<void>(resolve => { release = resolve; });
    await page.reload();
    await expect(page.getByRole("button", { name: "重置对话" })).toBeEnabled();
    await page.getByRole("button", { name: "重置对话" }).click();
    await expect(shells).toHaveCount(0);
    release(); hold = false;
    await expect(shells).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: `output/playwright/issue268-reset-${width}.png`, fullPage: true });
  });
}
