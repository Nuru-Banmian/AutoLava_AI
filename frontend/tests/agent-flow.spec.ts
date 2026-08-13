import { expect, test, type Page } from "@playwright/test";

type ChatMessage = { role: "user" | "assistant"; content: string };

const stores = [
  {
    id: 1,
    name: "罗马门店",
    timezone: "Europe/Rome",
    wash_count_enabled: true,
    company_settlement_enabled: true,
  },
  {
    id: 2,
    name: "米兰门店",
    timezone: "Europe/Rome",
    wash_count_enabled: true,
    company_settlement_enabled: false,
  },
];

const deterministicAnswers: Record<string, string> = {
  "你好": "你好，我可以回答普通问题，也可以分析当前门店的经营数据。",
  "上个月总收入是多少？": "上个月台账营业额 €1,000，公司结算收入 €200，月度总收入 €1,200；待到账 €80 不计入总收入。",
  "上个月收入分类构成": "上个月收入分类构成为现金 €600、刷卡 €400，其他数据 €50 不计入营业额。",
  "按星期分析上个月日收入": "上个月星期一平均台账营业额 €120，星期二平均 €90；休息日未计入经营日平均值。",
};

async function mockAgentApi(page: Page) {
  const conversations = new Map<number, ChatMessage[]>([
    [1, []],
    [2, [
      { role: "user", content: "米兰历史问题" },
      { role: "assistant", content: "米兰历史回答" },
    ]],
  ]);
  let releaseFailure: (() => void) | undefined;

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
    if (path === "/api/stores/accessible") return json(stores);

    const match = path.match(/^\/api\/agent\/stores\/(\d+)\/(conversation|messages)$/);
    if (!match) return json({ detail: `unmocked ${request.method()} ${path}` }, 500);
    const storeId = Number(match[1]);
    const resource = match[2];

    if (resource === "conversation" && request.method() === "GET") {
      return json({ messages: conversations.get(storeId) ?? [] });
    }
    if (resource === "conversation" && request.method() === "DELETE") {
      conversations.set(storeId, []);
      return route.fulfill({ status: 204, body: "" });
    }
    if (resource === "messages" && request.method() === "POST") {
      const { content } = await request.postDataJSON() as { content: string };
      if (content === "模拟失败") {
        await new Promise<void>((resolve) => { releaseFailure = resolve; });
        return json({ detail: "AI 模型暂时不可用，请稍后重试" }, 503);
      }
      const answer = deterministicAnswers[content] ?? "确定性测试回答";
      conversations.set(storeId, [
        ...(conversations.get(storeId) ?? []),
        { role: "user", content },
        { role: "assistant", content: answer },
      ]);
      return json({ message: { role: "assistant", content: answer } });
    }
    return json({ detail: `unmocked ${request.method()} ${path}` }, 500);
  });

  return {
    releaseFailure() {
      releaseFailure?.();
    },
  };
}

async function send(page: Page, content: string) {
  await page.getByRole("textbox", { name: "消息" }).fill(content);
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByRole("log", { name: "对话消息" }).getByText(
    deterministicAnswers[content],
    { exact: true },
  )).toBeVisible();
}

test("administrator completes chat, business queries, refresh, reset, and store switching", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockAgentApi(page);
  await page.goto("/agent");

  await send(page, "你好");
  await send(page, "上个月总收入是多少？");
  await send(page, "上个月收入分类构成");
  await send(page, "按星期分析上个月日收入");

  await page.reload();
  const log = page.getByRole("log", { name: "对话消息" });
  await expect(log.getByText(deterministicAnswers["上个月总收入是多少？"], { exact: true })).toBeVisible();
  await expect(log.getByText(deterministicAnswers["上个月收入分类构成"], { exact: true })).toBeVisible();
  await expect(log.getByText(deterministicAnswers["按星期分析上个月日收入"], { exact: true })).toBeVisible();

  const storePicker = page.getByTestId("desktop-store-picker").getByLabel("门店");
  await storePicker.selectOption("2");
  await expect(log.getByText("米兰历史回答", { exact: true })).toBeVisible();
  await expect(log.getByText(deterministicAnswers["上个月总收入是多少？"], { exact: true })).toHaveCount(0);

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "重置对话" }).click();
  await expect(log.getByText("米兰历史回答", { exact: true })).toHaveCount(0);
  await expect(page.getByText("发送一条消息开始对话。", { exact: true })).toBeVisible();

  await storePicker.selectOption("1");
  await expect(log.getByText(deterministicAnswers["上个月总收入是多少？"], { exact: true })).toBeVisible();
});

test("sending state is visible and a safe failure restores the unsent message", async ({ page }) => {
  const api = await mockAgentApi(page);
  await page.goto("/agent");

  const textbox = page.getByRole("textbox", { name: "消息" });
  await textbox.fill("模拟失败");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByRole("status").filter({ hasText: "AI 正在回复…" })).toBeVisible();
  await expect(textbox).toBeDisabled();
  api.releaseFailure();

  await expect(page.getByRole("alert")).toHaveText("AI 模型暂时不可用，请稍后重试");
  await expect(textbox).toBeEnabled();
  await expect(textbox).toHaveValue("模拟失败");
  await expect(page.getByRole("log", { name: "对话消息" }).getByText("模拟失败", { exact: true })).toHaveCount(0);
});
