import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterAll, afterEach, beforeAll, expect, it } from "vitest";

import { AgentPanel } from "@/components/AgentPanel";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPanel(storeId = 7) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const rendered = render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <AgentPanel storeId={storeId} />
        <LocationProbe />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { client, ...rendered };
}

function renderMobileEntry(storeId = 7) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const rendered = render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <AgentPanel storeId={storeId} surface="mobile-entry" />
        <LocationProbe />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { client, ...rendered };
}

function renderMobileFlow(storeId = 7) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const rendered = render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <Routes>
          <Route
            path="/"
            element={<AgentPanel key="mobile-entry" storeId={storeId} surface="mobile-entry" />}
          />
          <Route path="/agent" element={<AgentPanel key="workspace" storeId={storeId} />} />
        </Routes>
        <LocationProbe />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { client, ...rendered };
}

function LocationProbe() {
  const location = useLocation();
  return (
    <section aria-label="当前位置">
      {location.pathname}|{JSON.stringify(location.state)}
    </section>
  );
}

const emptyState = {
  confirmed_period: null,
  pending_period: null,
  metrics: [],
  filters: {},
  comparison: null,
  pending_clarifications: [],
};

function conversation(
  id: number | null,
  messages: Array<{
    id: number;
    role: "user" | "assistant";
    content: string;
    action?:
      | {
          type: "open_business_records";
          start_month: string;
          end_month: string;
        }
      | Record<string, unknown>
      | null;
  }> = [],
) {
  return {
    id,
    messages: messages.map((message) => ({
      ...message,
      created_at: "2026-07-26T12:00:00Z",
    })),
    state: emptyState,
    created_at: id === null ? null : "2026-07-26T12:00:00Z",
    updated_at: id === null ? null : "2026-07-26T12:00:00Z",
  };
}

function investigationState() {
  return {
    ...emptyState,
    investigation_goal: "调查最近营业额变化",
    pending_period: { start: "2026-07-01", end: "2026-07-14" },
    pending_directions: ["确认期间后检查每日台账营业额"],
    evidence_references: [
      {
        reference: "ev_0123456789abcdef01234567",
        source: ["store_daily_records"],
        queried_at: "2026-07-14T10:30:00Z",
        data_version: "private-version-token",
        period: { start: "2026-06-01", end: "2026-06-30" },
        use_as_current_fact: false,
      },
    ],
    analysis_hypotheses: [],
  };
}

it("keeps a current investigation compact on the mobile home entry", async () => {
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () =>
      HttpResponse.json({
        ...conversation(8, [
          { id: 31, role: "user", content: "不要在首页展开的问题" },
          { id: 32, role: "assistant", content: "不要在首页展开的完整回答" },
        ]),
        state: investigationState(),
      }),
    ),
  );
  renderMobileEntry();

  expect(await screen.findByText("调查最近营业额变化")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "继续当前调查" })).toHaveAttribute("href", "/agent");
  expect(screen.queryByText("不要在首页展开的问题")).not.toBeInTheDocument();
  expect(screen.queryByText("不要在首页展开的完整回答")).not.toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: "向 Agent 提问" })).not.toBeInTheDocument();
});

it("starts an empty investigation from the mobile home entry and opens the full page", async () => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  let submittedQuestion: string | null = null;
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () => HttpResponse.json(conversation(null))),
    http.post("/api/agent/stores/7/turn", async ({ request }) => {
      submittedQuestion = ((await request.json()) as { question: string }).question;
      await pending;
      return HttpResponse.json({
        route: "answer",
        content: "已完成调查。",
        recovery_status: "retried",
        progress: [{ status: "investigating", message: "已核对经营证据" }],
        partial: {
          verified_facts: ["营业额数据已核对"],
          incomplete_directions: ["天气证据"],
          unknowns: ["仍需确认天气影响"],
        },
        conversation: conversation(9, [
          { id: 41, role: "user", content: "最近营业额怎么样？" },
          { id: 42, role: "assistant", content: "已完成调查。" },
        ]),
      });
    }),
  );
  renderMobileFlow();

  fireEvent.change(await screen.findByRole("textbox", { name: "向 Agent 提问" }), {
    target: { value: "最近营业额怎么样？" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送并打开调查" }));

  await waitFor(() => expect(submittedQuestion).toBe("最近营业额怎么样？"));
  await waitFor(() => expect(screen.getByLabelText("当前位置")).toHaveTextContent("/agent"));
  expect(screen.getByRole("status")).toHaveTextContent("正在理解问题");
  expect(screen.getByRole("textbox", { name: "向 Agent 提问" })).toBeDisabled();

  release();
  expect(await screen.findByText("已完成调查。")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("已核对经营证据");
  expect(screen.getByRole("status")).toHaveTextContent("已自动重试");
  expect(screen.getByRole("region", { name: "部分调查结果" })).toHaveTextContent(
    "营业额数据已核对",
  );
});

it("shows no conversation entry while the global Agent switch is off", async () => {
  server.use(http.get("/api/agent/status", () => HttpResponse.json({ enabled: false })));
  renderPanel();

  expect(await screen.findByText("Agent 当前未启用")).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: "向 Agent 提问" })).not.toBeInTheDocument();
});

it("shows progress before revealing one complete direct answer", async () => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () => HttpResponse.json(conversation(null))),
    http.post("/api/agent/stores/7/turn", async () => {
      await pending;
      return HttpResponse.json({
        route: "answer",
        content: "这是一次性出现的完整回答。",
        recovery_status: "none",
        progress: [{ status: "investigating", message: "已核对经营证据" }],
        partial: null,
        conversation: conversation(1, [
          { id: 1, role: "user", content: "你能做什么？" },
          { id: 2, role: "assistant", content: "这是一次性出现的完整回答。" },
        ]),
      });
    }),
  );
  renderPanel();

  fireEvent.change(await screen.findByRole("textbox", { name: "向 Agent 提问" }), {
    target: { value: "你能做什么？" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

  expect(screen.getByRole("status")).toHaveTextContent("正在理解问题");
  expect(screen.queryByText(/完整回答/)).not.toBeInTheDocument();
  release();
  expect(await screen.findByText("正在整理回答…")).toBeInTheDocument();
  expect(screen.queryByText(/完整回答/)).not.toBeInTheDocument();
  expect(await screen.findByText("这是一次性出现的完整回答。")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("已核对经营证据");
});

it("shows verified partial results, unknowns, and a redacted recovery status", async () => {
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () => HttpResponse.json(conversation(null))),
    http.post("/api/agent/stores/7/turn", () =>
      HttpResponse.json({
        route: "safe_failure",
        content: "目前只能提供部分调查结果。",
        recovery_status: "retried",
        progress: [{ status: "partial", message: "部分证据暂时无法取得" }],
        partial: {
          verified_facts: ["六月每日台账营业额为 €1,200"],
          incomplete_directions: ["经营日"],
          unknowns: ["经营日目前无法根据已返回证据判断"],
        },
        conversation: conversation(9, [
          { id: 51, role: "assistant", content: "目前只能提供部分调查结果。" },
        ]),
      }),
    ),
  );
  renderPanel();

  fireEvent.change(await screen.findByRole("textbox", { name: "向 Agent 提问" }), {
    target: { value: "深入调查六月经营表现" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

  const partial = await screen.findByRole("region", { name: "部分调查结果" });
  expect(partial).toHaveTextContent("六月每日台账营业额为 €1,200");
  expect(partial).toHaveTextContent("尚未完成：经营日");
  expect(partial).toHaveTextContent("经营日目前无法根据已返回证据判断");
  expect(screen.getByRole("status")).toHaveTextContent("已自动重试");
  expect(document.body).not.toHaveTextContent(/provider|模型|密钥|配置/i);
});

it("shows an inferred period and lets the user confirm it without retyping the question", async () => {
  let submittedQuestion: string | null = null;
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () =>
      HttpResponse.json({
        ...conversation(8),
        state: investigationState(),
      }),
    ),
    http.post("/api/agent/stores/7/turn", async ({ request }) => {
      submittedQuestion = ((await request.json()) as { question: string }).question;
      return HttpResponse.json({
        route: "answer",
        content: "已按确认期间继续调查。",
        recovery_status: "none",
        progress: [{ status: "investigating", message: "已确认期间并完成调查" }],
        partial: null,
        conversation: conversation(8, [
          { id: 41, role: "assistant", content: "已按确认期间继续调查。" },
        ]),
      });
    }),
  );
  renderPanel();

  expect(await screen.findByRole("region", { name: "待确认期间" })).toHaveTextContent(
    "2026-07-01 至 2026-07-14",
  );
  fireEvent.click(screen.getByRole("button", { name: "确认这个期间" }));

  await waitFor(() => expect(submittedQuestion).toBe("确认"));
  expect(await screen.findByText("已按确认期间继续调查。")).toBeInTheDocument();
});

it("expands readable evidence without exposing internal references or versions", async () => {
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () =>
      HttpResponse.json({
        ...conversation(8, [{ id: 32, role: "assistant", content: "六月营业额已核对。" }]),
        state: investigationState(),
      }),
    ),
  );
  renderPanel();

  const evidence = await screen.findByRole("group", { name: "调查证据" });
  fireEvent.click(within(evidence).getByText("经营数据 · 2026-06-01 至 2026-06-30"));
  expect(evidence).toHaveTextContent("查询时间");
  expect(evidence).toHaveTextContent("每日台账");
  expect(evidence).not.toHaveTextContent("ev_0123456789abcdef01234567");
  expect(evidence).not.toHaveTextContent("private-version-token");
});

it("renders a clarification as the completed turn and stays within its card", async () => {
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () => HttpResponse.json(conversation(null))),
    http.post("/api/agent/stores/7/turn", () =>
      HttpResponse.json({
        route: "clarify",
        content: "你想了解哪个时间范围？",
        conversation: conversation(1, [
          { id: 1, role: "user", content: "帮我看看" },
          { id: 2, role: "assistant", content: "你想了解哪个时间范围？" },
        ]),
      }),
    ),
  );
  renderPanel();

  fireEvent.change(await screen.findByRole("textbox", { name: "向 Agent 提问" }), {
    target: { value: "帮我看看" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

  expect(await screen.findByText("你想了解哪个时间范围？")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "门店 Agent" })).toHaveClass(
    "min-w-0",
    "overflow-hidden",
  );
});

it("shows only the readable business records action and navigates on activation", async () => {
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () =>
      HttpResponse.json(
        conversation(8, [
          { id: 31, role: "user", content: "查看去年的全部记录" },
          {
            id: 32,
            role: "assistant",
            content: "可查看所选月份的营业记录。",
            action: {
              type: "open_business_records",
              start_month: "2025-01",
              end_month: "2025-12",
            },
          },
        ]),
      ),
    ),
  );
  renderPanel();

  const action = await screen.findByRole("button", { name: "查看营业记录" });
  expect(screen.queryByText(/\/database|store_id|user_id/)).not.toBeInTheDocument();
  fireEvent.click(action);

  expect(screen.getByLabelText("当前位置")).toHaveTextContent(
    '/database|{"agentBusinessRecordsAction":{"type":"open_business_records","start_month":"2025-01","end_month":"2025-12"}}',
  );
});

it("does not render an action when the server payload contains an unsafe parameter", async () => {
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () =>
      HttpResponse.json(
        conversation(8, [
          {
            id: 32,
            role: "assistant",
            content: "不可信操作",
            action: {
              type: "open_business_records",
              start_month: "2025-01",
              end_month: "2025-12",
              url: "/database?store_id=999",
            },
          },
        ]),
      ),
    ),
  );
  renderPanel();

  expect(await screen.findByText("不可信操作")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "查看营业记录" })).not.toBeInTheDocument();
});

it("restores the complete current conversation from the server", async () => {
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () =>
      HttpResponse.json(
        conversation(8, [
          { id: 31, role: "user", content: "刷新前的问题" },
          { id: 32, role: "assistant", content: "刷新后仍然完整显示的回答" },
        ]),
      ),
    ),
  );

  renderPanel();

  expect(await screen.findByText("刷新前的问题")).toBeInTheDocument();
  expect(screen.getByText("刷新后仍然完整显示的回答")).toBeInTheDocument();
});

it("requires irreversible confirmation before starting a new investigation", async () => {
  let resets = 0;
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () =>
      HttpResponse.json(
        conversation(8, [
          { id: 31, role: "user", content: "即将删除的问题" },
          { id: 32, role: "assistant", content: "即将删除的回答" },
        ]),
      ),
    ),
    http.delete("/api/agent/stores/7/conversation", async ({ request }) => {
      expect(await request.json()).toEqual({
        confirmation: "permanently_delete",
      });
      resets += 1;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderPanel();

  await screen.findByText("即将删除的问题");
  fireEvent.click(screen.getByRole("button", { name: "开始新调查" }));
  expect(screen.getByRole("alertdialog")).toHaveTextContent("此操作不可恢复");
  expect(resets).toBe(0);
  fireEvent.click(screen.getByRole("button", { name: "取消" }));

  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(screen.getByText("即将删除的问题")).toBeInTheDocument();
  expect(screen.getByText("即将删除的回答")).toBeInTheDocument();
  expect(resets).toBe(0);

  fireEvent.click(screen.getByRole("button", { name: "开始新调查" }));
  fireEvent.click(screen.getByRole("button", { name: "永久删除并开始新调查" }));

  expect(await screen.findByText("当前调查为空")).toBeInTheDocument();
  expect(screen.queryByText("即将删除的问题")).not.toBeInTheDocument();
  expect(resets).toBe(1);
});

it("keeps an in-flight turn in its originating store cache after switching", async () => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.get("/api/agent/stores/7/conversation", () => HttpResponse.json(conversation(null))),
    http.get("/api/agent/stores/8/conversation", () =>
      HttpResponse.json(
        conversation(8, [
          { id: 80, role: "user", content: "八号门店的问题" },
          { id: 81, role: "assistant", content: "八号门店的回答" },
        ]),
      ),
    ),
    http.post("/api/agent/stores/7/turn", async () => {
      await pending;
      return HttpResponse.json({
        route: "answer",
        content: "七号门店的回答",
        recovery_status: "none",
        progress: [{ status: "investigating", message: "七号门店的调查进度" }],
        partial: null,
        conversation: conversation(7, [
          { id: 70, role: "user", content: "七号门店的问题" },
          { id: 71, role: "assistant", content: "七号门店的回答" },
        ]),
      });
    }),
  );
  const { client, rerender } = renderPanel(7);
  fireEvent.change(await screen.findByRole("textbox", { name: "向 Agent 提问" }), {
    target: { value: "七号门店的问题" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

  rerender(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <AgentPanel storeId={8} />
        <LocationProbe />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  expect(await screen.findByText("八号门店的回答")).toBeInTheDocument();
  expect(screen.queryByText("七号门店的问题")).not.toBeInTheDocument();
  release();
  await waitFor(() =>
    expect(
      client
        .getQueryData<ReturnType<typeof conversation>>(["agent", "conversation", 7])
        ?.messages.at(-1)?.content,
    ).toBe("七号门店的回答"),
  );
  expect(screen.getByText("八号门店的回答")).toBeInTheDocument();
  expect(screen.queryByText("七号门店的回答")).not.toBeInTheDocument();
  expect(screen.queryByText("七号门店的调查进度")).not.toBeInTheDocument();
});
