import { expect, type Page, test } from "@playwright/test";

type Message = {
  id: number;
  role: "user" | "assistant";
  content: string;
  action?: {
    type: "open_business_records";
    start_month: string;
    end_month: string;
  } | null;
  created_at: string;
};

const emptyState = {
  confirmed_period: null,
  pending_period: null,
  metrics: [],
  filters: {},
  comparison: null,
  pending_clarifications: [],
};

async function mockAgentApi(page: Page, role: "admin" | "user" = "admin") {
  let nextMessageId = 10;
  const messages = new Map<number, Message[]>([
    [
      1,
      [
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
          action: {
            type: "open_business_records",
            start_month: "2025-01",
            end_month: "2025-12",
          },
          created_at: "2026-07-26T12:00:01Z",
        },
      ],
    ],
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
      return json({ id: 1, username: role, role, is_owner: false });
    }
    if (path === "/api/stores/accessible") {
      return json([
        { id: 1, name: "Roma", timezone: "Europe/Rome" },
        { id: 2, name: "Milano", timezone: "Europe/Rome" },
      ]);
    }
    if (path === "/api/agent/status") return json({ enabled: true });
    if (/^\/api\/dashboard\/\d+$/.test(path)) return json([]);
    if (/^\/api\/database\/\d+\/records$/.test(path)) {
      return json({
        items: [],
        categories: [],
        sum_daily_revenue: 0,
        total: 0,
        page: 1,
        page_size: 200,
      });
    }
    if (/^\/api\/charts\/\d+$/.test(path)) {
      const start = url.searchParams.get("start");
      const end = url.searchParams.get("end");
      return json({
        kpis: {
          total_revenue: 0,
          record_days: 0,
          open_days: 0,
          average_revenue: 0,
          primary_categories: [],
          total_wash_count: null,
          average_ticket: null,
        },
        range: { start, end, bucket: "month" },
        comparison_kpis: null,
        income_summary: {
          daily_ledger_revenue: 0,
          confirmed_settlement_income: 0,
          total_income: 0,
          includes_settlement_income: false,
        },
        classified_included_total: 0,
        daily: [],
        categories: [],
        excluded_categories: [],
        monthly: [],
        weather: [],
        weekday: [],
      });
    }

    const conversationMatch = path.match(/^\/api\/agent\/stores\/(\d+)\/conversation$/);
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

test("ordinary users cannot see or invoke the Agent", async ({ page }) => {
  await mockAgentApi(page, "user");
  await page.goto("/");

  await expect(page.getByRole("region", { name: "门店 Agent" })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "向 Agent 提问" })).toHaveCount(0);
});

test("administrator restores, switches, and permanently clears a current investigation", async ({
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
  await expect(page.getByText("当前调查为空")).toBeVisible();
  await expect(page.getByRole("button", { name: "查看营业记录" })).toHaveCount(0);
  await storePicker.selectOption("1");
  await expect(page.getByText("之前的问题")).toBeVisible();

  await page.getByRole("button", { name: "开始新调查" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("此操作不可恢复");
  await dialog.getByRole("button", { name: "取消" }).click();
  await expect(page.getByText("之前的问题")).toBeVisible();

  await page.getByRole("button", { name: "开始新调查" }).click();
  await dialog.getByRole("button", { name: "永久删除并开始新调查" }).click();
  await expect(page.getByText("当前调查为空")).toBeVisible();
  await expect(page.getByText("之前的问题")).toHaveCount(0);
});

for (const viewport of [
  { name: "desktop", width: 1280, height: 900, keyboard: false },
  { name: "mobile", width: 390, height: 844, keyboard: true },
] as const) {
  test(`${viewport.name} business records action is user-triggered, prefills months, and does not overflow`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await mockAgentApi(page);
    await page.goto("/");

    const action = page.getByRole("button", { name: "查看营业记录" });
    await expect(action).toBeVisible();
    await expect(page).toHaveURL("/");
    if (viewport.keyboard) {
      await action.focus();
      await page.keyboard.press("Enter");
    } else {
      await action.click();
    }

    await expect(page).toHaveURL("/database");
    await expect(page.getByRole("heading", { name: "营业记录" })).toBeVisible();
    await expect(page.getByLabel("开始月份")).toHaveValue("2025-01");
    await expect(page.getByLabel("结束月份")).toHaveValue("2025-12");
    const horizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(horizontalOverflow).toBe(false);
  });
}
