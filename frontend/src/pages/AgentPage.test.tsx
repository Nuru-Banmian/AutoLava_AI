import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";

import { AgentPage } from "@/pages/AgentPage";
import { useStore } from "@/stores/StoreProvider";

vi.mock("@/stores/StoreProvider", () => ({ useStore: vi.fn() }));

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

it("lets an administrator exchange a basic AI chat message", async () => {
  vi.mocked(useStore).mockReturnValue({
    selected: { id: 7, name: "测试门店", timezone: "Europe/Rome" },
  } as ReturnType<typeof useStore>);
  server.use(http.post("/api/agent/stores/7/messages", async ({ request }) => {
    expect(await request.json()).toEqual({
      messages: [{ role: "user", content: "你好" }],
    });
    return HttpResponse.json({
      message: { role: "assistant", content: "你好，我是 AutoLava AI。" },
    });
  }));

  render(<AgentPage />);
  await userEvent.type(screen.getByRole("textbox", { name: "消息" }), "你好");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("你好，我是 AutoLava AI。")).toBeInTheDocument();
  expect(screen.getByText("你好")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "消息" })).toHaveValue("");
});

it("does not carry chat history into another store", async () => {
  vi.mocked(useStore).mockReturnValue({
    selected: { id: 7, name: "一店", timezone: "Europe/Rome" },
  } as ReturnType<typeof useStore>);
  server.use(http.post("/api/agent/stores/7/messages", () => HttpResponse.json({
    message: { role: "assistant", content: "一店回答" },
  })));
  const view = render(<AgentPage />);
  await userEvent.type(screen.getByRole("textbox", { name: "消息" }), "一店问题");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("一店回答")).toBeInTheDocument();

  vi.mocked(useStore).mockReturnValue({
    selected: { id: 8, name: "二店", timezone: "Europe/Rome" },
  } as ReturnType<typeof useStore>);
  view.rerender(<AgentPage />);

  expect(screen.queryByText("一店问题")).not.toBeInTheDocument();
  expect(screen.queryByText("一店回答")).not.toBeInTheDocument();
});

it("ignores an old store reply that finishes after the store changes", async () => {
  let releaseReply: (() => void) | undefined;
  const delayedReply = new Promise<void>((resolve) => { releaseReply = resolve; });
  vi.mocked(useStore).mockReturnValue({
    selected: { id: 7, name: "一店", timezone: "Europe/Rome" },
  } as ReturnType<typeof useStore>);
  server.use(http.post("/api/agent/stores/7/messages", async () => {
    await delayedReply;
    return HttpResponse.json({
      message: { role: "assistant", content: "迟到的一店回答" },
    });
  }));
  const view = render(<AgentPage />);
  await userEvent.type(screen.getByRole("textbox", { name: "消息" }), "一店问题");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  vi.mocked(useStore).mockReturnValue({
    selected: { id: 8, name: "二店", timezone: "Europe/Rome" },
  } as ReturnType<typeof useStore>);
  view.rerender(<AgentPage />);
  releaseReply?.();

  await waitFor(() => expect(screen.queryByText("迟到的一店回答")).not.toBeInTheDocument());
  expect(screen.queryByText("一店问题")).not.toBeInTheDocument();
});

it("keeps chatting after ten exchanges by sending only the recent context", async () => {
  vi.mocked(useStore).mockReturnValue({
    selected: { id: 7, name: "测试门店", timezone: "Europe/Rome" },
  } as ReturnType<typeof useStore>);
  const requestBodies: Array<{ messages: Array<{ role: string; content: string }> }> = [];
  server.use(http.post("/api/agent/stores/7/messages", async ({ request }) => {
    requestBodies.push(await request.json() as typeof requestBodies[number]);
    return HttpResponse.json({
      message: { role: "assistant", content: `回答${requestBodies.length}` },
    });
  }));
  render(<AgentPage />);

  for (let turn = 1; turn <= 11; turn += 1) {
    await userEvent.type(screen.getByRole("textbox", { name: "消息" }), `问题${turn}`);
    await userEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByText(`回答${turn}`);
  }

  expect(requestBodies).toHaveLength(11);
  expect(requestBodies.at(-1)?.messages).toHaveLength(19);
  expect(requestBodies.at(-1)?.messages.at(0)?.role).toBe("user");
  expect(requestBodies.at(-1)?.messages.map((message) => message.role)).toEqual(
    Array.from({ length: 19 }, (_, index) => index % 2 === 0 ? "user" : "assistant"),
  );
  expect(requestBodies.at(-1)?.messages.at(-1)).toEqual({
    role: "user",
    content: "问题11",
  });
  expect(screen.getByText("问题1")).toBeInTheDocument();
  expect(screen.getByText("回答11")).toBeInTheDocument();
});
