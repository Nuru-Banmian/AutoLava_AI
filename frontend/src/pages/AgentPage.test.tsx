import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";

import { AgentPage } from "@/pages/AgentPage";
import { useStore } from "@/stores/StoreProvider";

vi.mock("@/stores/StoreProvider", () => ({ useStore: vi.fn() }));

const server = setupServer(
  http.get("/api/agent/stores/:storeId/conversation", () =>
    HttpResponse.json({ messages: [] }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});
afterAll(() => server.close());

function selectStore(id: number, name = "测试门店") {
  vi.mocked(useStore).mockReturnValue({
    selected: { id, name, timezone: "Europe/Rome" },
  } as ReturnType<typeof useStore>);
}

it("restores the complete saved conversation when the page opens", async () => {
  selectStore(7);
  const messages = Array.from({ length: 22 }, (_, index) => ({
    role: index % 2 === 0 ? "user" as const : "assistant" as const,
    content: `历史消息${index + 1}`,
  }));
  server.use(
    http.get("/api/agent/stores/7/conversation", () =>
      HttpResponse.json({ messages }),
    ),
  );

  render(<AgentPage />);

  expect(await screen.findByText("历史消息1")).toBeInTheDocument();
  expect(screen.getByText("历史消息22")).toBeInTheDocument();
});

it("sends only the new message and appends the saved reply", async () => {
  selectStore(7);
  server.use(http.post("/api/agent/stores/7/messages", async ({ request }) => {
    expect(await request.json()).toEqual({ content: "你好" });
    return HttpResponse.json({
      message: { role: "assistant", content: "你好，我是 AutoLava AI。" },
    });
  }));

  render(<AgentPage />);
  await screen.findByText("发送一条消息开始对话。");
  await userEvent.type(screen.getByRole("textbox", { name: "消息" }), "你好");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("你好，我是 AutoLava AI。")).toBeInTheDocument();
  expect(screen.getByText("你好")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "消息" })).toHaveValue("");
});

it("does not send while the complete history could not be loaded", async () => {
  selectStore(7);
  server.use(
    http.get("/api/agent/stores/7/conversation", () =>
      HttpResponse.json({ detail: "unavailable" }, { status: 503 }),
    ),
  );

  render(<AgentPage />);

  expect(await screen.findByRole("alert")).toHaveTextContent("服务器暂时不可用");
  expect(screen.getByRole("textbox", { name: "消息" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "重置对话" })).toBeDisabled();
});

it("loads each store conversation again when stores change", async () => {
  selectStore(7, "一店");
  server.use(
    http.get("/api/agent/stores/7/conversation", () => HttpResponse.json({
      messages: [{ role: "user", content: "一店历史" }],
    })),
    http.get("/api/agent/stores/8/conversation", () => HttpResponse.json({
      messages: [{ role: "user", content: "二店历史" }],
    })),
  );
  const view = render(<AgentPage />);
  expect(await screen.findByText("一店历史")).toBeInTheDocument();

  selectStore(8, "二店");
  view.rerender(<AgentPage />);

  expect(await screen.findByText("二店历史")).toBeInTheDocument();
  expect(screen.queryByText("一店历史")).not.toBeInTheDocument();

  selectStore(7, "一店");
  view.rerender(<AgentPage />);
  expect(await screen.findByText("一店历史")).toBeInTheDocument();
});

it("ignores an old store history response that finishes after the store changes", async () => {
  let releaseHistory: (() => void) | undefined;
  const delayedHistory = new Promise<void>((resolve) => { releaseHistory = resolve; });
  selectStore(7, "一店");
  server.use(
    http.get("/api/agent/stores/7/conversation", async () => {
      await delayedHistory;
      return HttpResponse.json({ messages: [{ role: "user", content: "迟到的一店历史" }] });
    }),
    http.get("/api/agent/stores/8/conversation", () =>
      HttpResponse.json({ messages: [{ role: "user", content: "二店历史" }] }),
    ),
  );
  const view = render(<AgentPage />);

  selectStore(8, "二店");
  view.rerender(<AgentPage />);
  expect(await screen.findByText("二店历史")).toBeInTheDocument();
  releaseHistory?.();

  await waitFor(() =>
    expect(screen.queryByText("迟到的一店历史")).not.toBeInTheDocument(),
  );
});

it("resets only after explicit confirmation", async () => {
  selectStore(7);
  let deleteCalls = 0;
  server.use(
    http.get("/api/agent/stores/7/conversation", () => HttpResponse.json({
      messages: [{ role: "user", content: "需要保留的历史" }],
    })),
    http.delete("/api/agent/stores/7/conversation", () => {
      deleteCalls += 1;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  render(<AgentPage />);
  expect(await screen.findByText("需要保留的历史")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "重置对话" }));
  expect(confirm).toHaveBeenCalled();
  expect(deleteCalls).toBe(0);
  expect(screen.getByText("需要保留的历史")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "重置对话" }));
  await waitFor(() => expect(deleteCalls).toBe(1));
  expect(screen.queryByText("需要保留的历史")).not.toBeInTheDocument();
  expect(screen.getByText("发送一条消息开始对话。")).toBeInTheDocument();
});
