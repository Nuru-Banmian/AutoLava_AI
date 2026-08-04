import { expect, test, type Page, type Route } from "@playwright/test";

type Conversation = {
  conversation_id: number;
  store_id: number;
  store_name: string;
  messages: {
    id: number;
    role: "user" | "assistant";
    content: string;
    created_at: string;
  }[];
  latest_turn: {
    id: number;
    status: "running" | "completed";
    error_message: null;
    started_at: string;
    finished_at: string | null;
    investigation_cards: {
      operation: string;
      range_start: string | null;
      range_end: string | null;
      filters: string[];
      status: "completed";
    }[];
  } | null;
};

const stores = [
  { id: 1, name: "罗马总店", timezone: "Europe/Rome" },
  { id: 2, name: "米兰分店", timezone: "Europe/Rome" },
];

function emptyConversation(storeId = 1): Conversation {
  return {
    conversation_id: storeId,
    store_id: storeId,
    store_name: stores[storeId - 1].name,
    messages: [],
    latest_turn: null,
  };
}

function runningConversation(): Conversation {
  return {
    ...emptyConversation(),
    messages: [{
      id: 1,
      role: "user",
      content: "分析本月营业额",
      created_at: "2026-07-30T10:00:00",
    }],
    latest_turn: {
      id: 7,
      status: "running",
      error_message: null,
      started_at: "2026-07-30T10:00:00",
      finished_at: null,
      investigation_cards: [],
    },
  };
}

function completedConversation(storeId = 1): Conversation {
  const store = stores[storeId - 1];
  return {
    ...emptyConversation(storeId),
    messages: [
      {
        id: storeId * 10 + 1,
        role: "user",
        content: "分析本月营业额",
        created_at: "2026-07-30T10:00:00",
      },
      {
        id: storeId * 10 + 2,
        role: "assistant",
        content: storeId === 1
          ? "本月台账营业额为 120 欧元。"
          : "米兰分店当前没有匹配记录。",
        created_at: "2026-07-30T10:00:02",
      },
    ],
    latest_turn: {
      id: storeId * 10 + 7,
      status: "completed",
      error_message: null,
      started_at: "2026-07-30T10:00:00",
      finished_at: "2026-07-30T10:00:02",
      investigation_cards: [{
        operation: "汇总经营表现",
        range_start: "2026-07-01",
        range_end: "2026-07-30",
        filters: [],
        status: "completed",
      }],
    },
  };
}

function longConversation(): Conversation {
  return {
    ...completedConversation(),
    messages: Array.from({ length: 40 }, (_, index) => ({
      id: index + 1,
      role: index % 2 === 0 ? "user" as const : "assistant" as const,
      content: `第 ${index + 1} 条经营分析消息，用于确认长对话只在对话内容区滚动。`,
      created_at: "2026-07-30T10:00:00",
    })),
  };
}

async function mockAgentApi(
  page: Page,
  conversation: (storeId: number) => Conversation,
) {
  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (value: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(value),
    });

    if (path === "/api/auth/me") {
      return json({
        id: 1,
        username: "administrator",
        role: "admin",
        is_owner: true,
      });
    }
    if (path === "/api/stores/accessible") return json(stores);
    const currentStore = path.match(/^\/api\/agent\/stores\/(\d+)$/);
    if (currentStore) {
      const store = stores[Number(currentStore[1]) - 1];
      return json({ store_id: store.id, store_name: store.name });
    }
    const currentConversation = path.match(
      /^\/api\/agent\/stores\/(\d+)\/conversation$/,
    );
    if (currentConversation && request.method() === "GET") {
      return json(conversation(Number(currentConversation[1])));
    }
    if (currentConversation && request.method() === "DELETE") {
      return route.fulfill({ status: 204 });
    }
    return json({ detail: `unmocked ${request.method()} ${path}` }, 500);
  });
}

async function installAgentStream(page: Page) {
  await page.addInitScript(() => {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const rawUrl = typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
      const url = new URL(rawUrl, window.location.origin);
      if (
        init?.method === "POST"
        && /^\/api\/agent\/stores\/1\/messages$/.test(url.pathname)
      ) {
        const encoder = new TextEncoder();
        const events = [
          { type: "started", turn_id: 7 },
          {
            type: "phase",
            turn_id: 7,
            phase: "querying_data",
          },
          {
            type: "investigation_card",
            turn_id: 7,
            card: {
              operation: "汇总经营表现",
              range_start: "2026-07-01",
              range_end: "2026-07-30",
              filters: [],
              status: "completed",
            },
          },
          {
            type: "phase",
            turn_id: 7,
            phase: "processing_data",
          },
          {
            type: "phase",
            turn_id: 7,
            phase: "preparing_answer",
          },
          {
            type: "answer_delta",
            turn_id: 7,
            delta: "本月台账营业额",
          },
          {
            type: "answer_delta",
            turn_id: 7,
            delta: "为 120 欧元。",
          },
          { type: "completed", turn_id: 7 },
        ];
        return new Response(new ReadableStream({
          async start(controller) {
            await nativeFetch("/__agent-test/started");
            for (const event of events) {
              await new Promise((resolve) => setTimeout(resolve, 250));
              if (event.type === "completed") {
                await nativeFetch("/__agent-test/completed");
              }
              controller.enqueue(
                encoder.encode(`${JSON.stringify(event)}\n`),
              );
            }
            await new Promise((resolve) => setTimeout(resolve, 350));
            controller.close();
          },
        }), {
          headers: { "content-type": "application/x-ndjson" },
        });
      }
      return nativeFetch(input, init);
    };
  });
}

async function fulfillSignal(route: Route) {
  await route.fulfill({ status: 204 });
}

test("streams phases, cards and answer while enforcing one active turn", async ({
  page,
}) => {
  let current = emptyConversation();
  await page.route("**/__agent-test/started", async (route) => {
    current = runningConversation();
    await fulfillSignal(route);
  });
  await page.route("**/__agent-test/completed", async (route) => {
    current = completedConversation();
    await fulfillSignal(route);
  });
  await mockAgentApi(page, () => current);
  await installAgentStream(page);
  await page.goto("/agent");

  const input = page.getByRole("textbox", { name: "向 Agent 提问" });
  await input.fill("分析本月营业额");
  await input.press("Enter");

  await expect(page.getByRole("button", { name: "正在回答…" }))
    .toBeDisabled();
  await expect(page.getByRole("status")).toHaveText("正在查询数据…");
  await expect(page.getByRole("region", { name: "调查过程" }))
    .toContainText("汇总经营表现");
  await expect(page.getByRole("status")).toHaveText("正在处理数据…");
  await expect(page.getByRole("status")).toHaveText("正在准备回答…");
  await expect(page.getByText("本月台账营业额为 120 欧元。"))
    .toBeVisible();
  await expect(page.getByRole("status")).toHaveText("回答已完成");
  const readySend = page.getByRole("button", { name: "发送" });
  await expect(readySend).toBeVisible();
  await input.fill("继续分析");
  await expect(readySend).toBeEnabled();
});

test("refresh restores a running turn and then its persisted completion", async ({
  page,
}) => {
  let reads = 0;
  await mockAgentApi(page, () => {
    reads += 1;
    return reads < 3 ? runningConversation() : completedConversation();
  });

  await page.goto("/agent");
  await expect(page.getByText("后台处理中，正在恢复结果…")).toBeVisible();
  await page.reload();
  await expect(page.getByText("后台处理中，正在恢复结果…")).toBeVisible();
  await expect(
    page.getByText("本月台账营业额为 120 欧元。"),
  ).toBeVisible({ timeout: 3_000 });
  expect(reads).toBeGreaterThanOrEqual(3);
});

test("narrow layout remains contained and store switching clears the draft", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await mockAgentApi(page, (storeId) => completedConversation(storeId));
  await page.goto("/agent");

  const input = page.getByRole("textbox", { name: "向 Agent 提问" });
  await input.fill("尚未发送的草稿");
  await page.getByTestId("mobile-store-picker")
    .getByRole("combobox", { name: "门店" })
    .selectOption("2");

  await expect(page.getByText("米兰分店当前没有匹配记录。"))
    .toBeVisible();
  await expect(input).toHaveValue("");
  await input.fill("移动端换行");
  await input.press("Enter");
  await expect(input).toHaveValue("移动端换行\n");
  await expect.poll(() => page.evaluate(() => ({
    body: document.body.scrollWidth,
    document: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  }))).toEqual({ body: 320, document: 320, viewport: 320 });
});

test("desktop fills the available viewport and scrolls only the conversation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 900 });
  await mockAgentApi(page, () => longConversation());
  await page.goto("/agent");

  const workspace = page.getByRole("region", { name: "Agent 工作区" });
  const conversation = page.getByRole("region", { name: "Agent 对话内容" });
  await expect(workspace).toBeVisible();
  await expect(conversation).toBeVisible();
  await expect.poll(() => page.evaluate(() => ({
    documentHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
    scrollY: window.scrollY,
  }))).toEqual({ documentHeight: 900, viewportHeight: 900, scrollY: 0 });
  await expect.poll(() => conversation.evaluate(
    (node) => node.scrollHeight > node.clientHeight,
  )).toBe(true);

  await conversation.evaluate((node) => node.scrollTo({ top: node.scrollHeight }));
  expect(await page.evaluate(() => window.scrollY)).toBe(0);

  const [resetBox, sendBox, workspaceBox] = await Promise.all([
    page.getByRole("button", { name: "重置会话" }).boundingBox(),
    page.getByRole("button", { name: "发送" }).boundingBox(),
    workspace.boundingBox(),
  ]);
  expect(resetBox).not.toBeNull();
  expect(sendBox).not.toBeNull();
  expect(workspaceBox).not.toBeNull();
  expect(1920 - workspaceBox!.x - workspaceBox!.width)
    .toBeLessThanOrEqual(24);
  expect(resetBox!.x).toBeLessThan(sendBox!.x);
  expect(Math.abs(resetBox!.y - sendBox!.y)).toBeLessThanOrEqual(1);
  expect(workspaceBox!.x + workspaceBox!.width - sendBox!.x - sendBox!.width)
    .toBeLessThanOrEqual(1);
});

test("mobile keeps long conversations inside the conversation scroller", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await mockAgentApi(page, () => longConversation());
  await page.goto("/agent");

  const conversation = page.getByRole("region", { name: "Agent 对话内容" });
  await expect(conversation).toBeVisible();
  await expect.poll(() => page.evaluate(() => ({
    documentHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
    scrollY: window.scrollY,
  }))).toEqual({ documentHeight: 700, viewportHeight: 700, scrollY: 0 });
  await expect.poll(() => conversation.evaluate(
    (node) => node.scrollHeight > node.clientHeight,
  )).toBe(true);
});
