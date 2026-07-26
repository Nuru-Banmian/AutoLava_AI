import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it } from "vitest";

import { AgentPanel } from "@/components/AgentPanel";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <AgentPanel storeId={7} />
    </QueryClientProvider>,
  );
}

it("shows no conversation entry while the global Agent switch is off", async () => {
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: false })),
  );
  renderPanel();

  expect(await screen.findByText("Agent 当前未启用")).toBeInTheDocument();
  expect(
    screen.queryByRole("textbox", { name: "向 Agent 提问" }),
  ).not.toBeInTheDocument();
});

it("shows progress before revealing one complete direct answer", async () => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.post("/api/agent/stores/7/turn", async () => {
      await pending;
      return HttpResponse.json({
        route: "answer",
        content: "这是一次性出现的完整回答。",
      });
    }),
  );
  renderPanel();

  fireEvent.change(
    await screen.findByRole("textbox", { name: "向 Agent 提问" }),
    { target: { value: "你能做什么？" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

  expect(screen.getByRole("status")).toHaveTextContent("正在理解问题");
  expect(screen.queryByText(/完整回答/)).not.toBeInTheDocument();
  release();
  expect(await screen.findByText("正在整理回答…")).toBeInTheDocument();
  expect(screen.queryByText(/完整回答/)).not.toBeInTheDocument();
  expect(
    await screen.findByText("这是一次性出现的完整回答。"),
  ).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("renders a clarification as the completed turn and stays within its card", async () => {
  server.use(
    http.get("/api/agent/status", () => HttpResponse.json({ enabled: true })),
    http.post("/api/agent/stores/7/turn", () =>
      HttpResponse.json({
        route: "clarify",
        content: "你想了解哪个时间范围？",
      }),
    ),
  );
  renderPanel();

  fireEvent.change(
    await screen.findByRole("textbox", { name: "向 Agent 提问" }),
    { target: { value: "帮我看看" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

  expect(
    await screen.findByText("你想了解哪个时间范围？"),
  ).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "门店 Agent" })).toHaveClass(
    "min-w-0",
    "overflow-hidden",
  );
});
