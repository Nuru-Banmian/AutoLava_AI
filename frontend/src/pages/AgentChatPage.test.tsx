import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { advanceSessionScope } from "@/auth/sessionScope";
import { AgentChatPage } from "./AgentChatPage";

let storeId = 1;
vi.mock("@/auth/AuthProvider", () => ({ useAuth: () => ({ user: { id: 1, role: "admin" } }) }));
vi.mock("@/stores/StoreProvider", () => ({ useStore: () => ({ selected: { id: storeId, name: `门店${storeId}` } }) }));

class EventStream extends EventTarget {
  static streams: EventStream[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) { super(); EventStream.streams.push(this); }
  close() { this.closed = true; }
  emit(kind: string, data: object) { this.dispatchEvent(new MessageEvent(kind, { data: JSON.stringify(data) })); }
}

const run = { id: "run-1", status: "running", output: "", error_code: null, model: "test", calls: 1, usage: null };
const server = setupServer();

beforeEach(() => {
  storeId = 1;
  EventStream.streams = [];
  vi.stubGlobal("EventSource", EventStream);
  server.listen({ onUnhandledRequest: "error" });
  server.use(http.get("/api/agent/:store/conversation", () => HttpResponse.json({ messages: [], run: null })));
});
afterEach(() => { server.resetHandlers(); server.close(); vi.unstubAllGlobals(); });

describe("AI conversation", () => {
  it("submits once, renders streamed text, then reads saved completion", async () => {
    let calls = 0;
    let done = false;
    server.use(
      http.get("/api/agent/1/conversation", () => HttpResponse.json({
        messages: done ? [{ id: 1, role: "assistant", content: "完整回答" }] : [],
        run: calls ? { ...run, status: done ? "completed" : "running" } : null,
      })),
      http.post("/api/agent/1/messages", () => { calls++; return HttpResponse.json(run, { status: 202 }); }),
    );
    render(<AgentChatPage />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.queryByText("正在读取对话…")).not.toBeInTheDocument());
    await user.type(screen.getByLabelText("发送消息"), "你好");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByText("正在生成回答…");
    await waitFor(() => expect(EventStream.streams.length).toBeGreaterThan(0));
    act(() => EventStream.streams.at(-1)!.emit("delta", { text: "部分回答" }));
    expect(screen.getByText("部分回答")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    done = true;
    act(() => EventStream.streams.at(-1)!.emit("completed", { status: "completed" }));
    await screen.findByText("完整回答");
    expect(screen.getByText("回答已完成并保存")).toBeInTheDocument();
    expect(calls).toBe(1);
  });

  it("restores active output and discards events after store or session switches", async () => {
    server.use(http.get("/api/agent/1/conversation", () => HttpResponse.json({
      messages: [{ id: 1, role: "user", content: "门店1的问题" }], run: { ...run, output: "已保存片段" },
    })));
    const page = render(<AgentChatPage />);
    await screen.findByText("已保存片段");
    await waitFor(() => expect(EventStream.streams).toHaveLength(1));
    const old = EventStream.streams[0];
    storeId = 2;
    page.rerender(<AgentChatPage />);
    await waitFor(() => expect(screen.queryByText("正在读取对话…")).not.toBeInTheDocument());
    act(() => old.emit("delta", { text: "门店1的迟到内容" }));
    expect(old.closed).toBe(true);
    expect(screen.queryByText(/门店1的问题|门店1的迟到内容|已保存片段/)).not.toBeInTheDocument();
    storeId = 1;
    page.rerender(<AgentChatPage />);
    await screen.findByText("已保存片段");
    await waitFor(() => expect(EventStream.streams).toHaveLength(2));
    act(() => { advanceSessionScope(); EventStream.streams[1].emit("delta", { text: "旧会话内容" }); });
    expect(screen.queryByText("旧会话内容")).not.toBeInTheDocument();
  });

  it("shows a persisted failure without submitting or opening another model stream", async () => {
    server.use(http.get("/api/agent/1/conversation", () => HttpResponse.json({
      messages: [], run: { ...run, status: "failed", error_code: "model_not_configured" },
    })));
    render(<AgentChatPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("聊天模型尚未配置");
    expect(EventStream.streams).toHaveLength(0);
  });
});
