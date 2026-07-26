import { expect, test, type Page } from "@playwright/test";

type Message = {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

const emptyState = {
  confirmed_period: null,
  metrics: [],
  filters: {},
  comparison: null,
  pending_clarifications: [],
};

async function mockAgentApi(page: Page) {
  let nextMessageId = 10;
  const messages = new Map<number, Message[]>([
    [1, [
      {
        id: 1,
        role: "user",
        content: "之前的问题",
        created_at: "2026-07-26T12:00:00Z",
      },
      {
        id: 2,
        role: "assistant",
        content: "之前保存的完整回答",
        created_at: "2026-07-26T12:00:01Z",
      },
    ]],
    [2, []],
  ]);
  const snapshot = (storeId: number) => {
    const current = messages.get(storeId) ?? [];
    return {
      id: current.length ? storeId : null,
      messages: current,
      state: emptyState,
      created_at: current.length ? "2026-07-26T12:00:00Z" : null,
      updated_at: current.length ? "2026-07-26T12:00:01Z" : null,
    };
  };

  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (value: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(value),
      });

    if (path === "/api/auth/me") {
      return json({ id: 1, username: "admin", role: "admin", is_owner: false });
    }
    if (path === "/api/stores/accessible") {
      return json([
        { id: 1, name: "Roma", timezone: "Europe/Rome" },
        { id: 2, name: "Milano", timezone: "Europe/Rome" },
      ]);
    }
    if (path === "/api/agent/status") return json({ enabled: true });
    if (/^\/api\/dashboard\/\d+$/.test(path)) return json([]);

    const conversationMatch = path.match(
      /^\/api\/agent\/stores\/(\d+)\/conversation$/,
    );
    if (conversationMatch) {
      const storeId = Number(conversationMatch[1]);
      if (request.method() === "GET") return json(snapshot(storeId));
      if (request.method() === "DELETE") {
        messages.set(storeId, []);
        return route.fulfill({ status: 204 });
      }
    }
    const turnMatch = path.match(/^\/api\/agent\/stores\/(\d+)\/turn$/);
    if (turnMatch && request.method() === "POST") {
      const storeId = Number(turnMatch[1]);
      const body = request.postDataJSON() as { question: string };
      const current = messages.get(storeId) ?? [];
      current.push(
        {
          id: nextMessageId++,
          role: "user",
          content: body.question,
          created_at: "2026-07-26T12:01:00Z",
        },
        {
          id: nextMessageId++,
          role: "assistant",
          content: `${storeId}号门店的完整回答`,
          created_at: "2026-07-26T12:01:01Z",
        },
      );
      messages.set(storeId, current);
      return json({
        route: "answer",
        content: `${storeId}号门店的完整回答`,
        conversation: snapshot(storeId),
      });
    }
    return json({ detail: `unmocked ${request.method()} ${path}` }, 500);
  });
}

test("administrator restores, switches, and permanently resets per-store conversations", async ({
  page,
}) => {
  await mockAgentApi(page);
  await page.goto("/");

  await expect(page.getByText("之前保存的完整回答")).toBeVisible();
  await page.getByLabel("向 Agent 提问").fill("刷新后也要保留");
  await page.getByRole("button", { name: "发送问题" }).click();
  await expect(page.getByText("1号门店的完整回答")).toBeVisible();

  await page.reload();
  await expect(page.getByText("刷新后也要保留")).toBeVisible();
  await expect(page.getByText("1号门店的完整回答")).toBeVisible();

  const storePicker = page
    .getByTestId("desktop-store-picker")
    .getByRole("combobox", { name: "门店" });
  await storePicker.selectOption("2");
  await expect(page.getByText("当前对话为空")).toBeVisible();
  await storePicker.selectOption("1");
  await expect(page.getByText("之前的问题")).toBeVisible();

  await page.getByRole("button", { name: "重置对话" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("此操作不可恢复");
  await dialog.getByRole("button", { name: "确认永久重置" }).click();
  await expect(page.getByText("当前对话为空")).toBeVisible();
  await expect(page.getByText("之前的问题")).toHaveCount(0);
});
