import { expect, test } from "@playwright/test";

// These browser checks exercise the rendered page and native EventSource with
// controlled HTTP/SSE responses. Backend pagination has separate API coverage.
for (const width of [390, 1280]) {
  test(`pagination partial progress and saved answer survive refresh at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    const question = "请查询所有经营记录";
    const progress = "上下文容量不足，剩余结果未读取，请缩小查询范围。";
    const answer = "部分完成：本轮仅读取 2 / 8 行，剩余 6 行未读取。请缩小查询范围后继续。";
    const run = { id: "pagination-run", request_id: "pagination-request", status: "running", output: "", error_code: null, model: "controlled-browser", calls: 1, usage: null };
    let submitted = 0;
    let completed = false;
    let streams = 0;
    const unexpected: string[] = [];
    const browserErrors: string[] = [];
    page.on("pageerror", (error) => browserErrors.push(error.message));
    let releaseEvents!: () => void;
    const eventsReady = new Promise<void>((resolve) => { releaseEvents = resolve; });

    await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const json = (body: unknown, status = 200) => route.fulfill({
        status, contentType: "application/json", body: JSON.stringify(body),
      });
      if (path === "/api/auth/me") return json({ id: 1, username: "pagination-admin", role: "admin", is_owner: true });
      if (path === "/api/stores/accessible") return json([{ id: 1, name: "分页验收门店", timezone: "Asia/Shanghai", wash_count_enabled: true }]);
      if (path === "/api/agent/1/memory-jobs") return json({ items: [], next_before: null });
      if (path === "/api/agent/1/conversation") return json({
        generation: 0, next_before: null,
        messages: submitted ? [
          { id: 1, role: "user", content: question },
          ...(completed ? [{ id: 2, role: "assistant", content: answer }] : []),
        ] : [],
        run: submitted ? { ...run, status: completed ? "completed" : "running", output: completed ? answer : "" } : null,
      });
      if (path === "/api/agent/1/messages" && request.method() === "POST") {
        expect(request.postDataJSON().content).toBe(question);
        submitted++;
        return json(run, 202);
      }
      if (path === "/api/agent/1/runs/pagination-run/events") {
        streams++;
        await eventsReady;
        completed = true;
        const event = (id: number, name: string, data: unknown) => `id: ${id}\nevent: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
        return route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: event(1, "tool", { name: "store_query", status: "partial", message: progress, failures: [{ code: "context_capacity" }] })
            + event(2, "delta", { text: answer })
            + event(3, "completed", { status: "completed" }),
        });
      }
      unexpected.push(`${request.method()} ${path}`);
      return json({ detail: "Unexpected pagination browser request" }, 500);
    });

    await page.goto("/ai");
    await expect(page.getByRole("heading", { name: "AI 对话" })).toBeVisible();
    await expect(page.getByRole("button", { name: "重置对话" })).toBeEnabled();
    await page.getByLabel("发送消息").fill(question);
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect(page.getByText("正在生成回答…", { exact: true })).toBeVisible();
    await expect.poll(() => streams).toBe(1);
    releaseEvents();
    await expect(page.getByText(`查询部分完成：${progress}`, { exact: true })).toBeVisible();
    await expect(page.getByText("回答已完成并保存", { exact: true })).toBeVisible();
    await expect(page.getByText(answer, { exact: true })).toBeVisible();
    await expect(page.getByText("本次工具请求未获执行", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    const progressText = page.getByText(`查询部分完成：${progress}`, { exact: true });
    await progressText.scrollIntoViewIfNeeded();
    if (width < 768) {
      const progressBox = await progressText.boundingBox();
      const navigationBox = await page.getByRole("navigation", { name: "移动导航" }).boundingBox();
      expect(progressBox!.y + progressBox!.height).toBeLessThanOrEqual(navigationBox!.y);
    }
    await page.screenshot({ path: testInfo.outputPath("issue-265-partial-progress.png") });

    await page.reload();
    await expect(page.getByText(answer, { exact: true })).toBeVisible();
    await expect(page.getByText("回答已完成并保存", { exact: true })).toBeVisible();
    await expect(page.getByText("正在生成回答…", { exact: true })).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    expect(submitted).toBe(1);
    expect(streams).toBe(1);
    expect(unexpected).toEqual([]);
    expect(browserErrors).toEqual([]);
    await page.getByText(answer, { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath("issue-265-partial-refresh.png") });
  });
}
