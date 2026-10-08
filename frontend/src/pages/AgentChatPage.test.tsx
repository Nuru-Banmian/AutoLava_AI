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
  it("shows scoped skill and query progress from persisted events", async () => {
    server.use(http.get("/api/agent/1/conversation", () => HttpResponse.json({
      generation: 0, messages: [], run,
    })));
    render(<AgentChatPage />);
    await waitFor(() => expect(EventStream.streams).toHaveLength(1));
    act(() => EventStream.streams[0].emit("tool", { name: "read_skill", status: "completed" }));
    expect(screen.getByText("已读取经营分析技能")).toBeInTheDocument();
    act(() => EventStream.streams[0].emit("tool", {
      name: "store_overview", status: "completed", range: { start: "2026-07-10", end: "2026-07-14" },
    }));
    expect(screen.getByText("已查询经营概览：2026-07-10 至 2026-07-14")).toBeInTheDocument();
  });
  it("starts a new run on the first retry after a lost response was reconciled as failed", async () => {
    const ids: string[] = [];
    server.use(
      http.get("/api/agent/1/conversation", () => HttpResponse.json({
        generation: 0, messages: ids.length ? [{ id: 1, role: "user", content: "重试问题" }] : [],
        run: ids.length ? { ...run, request_id: ids.at(-1), status: "failed", error_code: "interrupted" } : null,
      })),
      http.post("/api/agent/1/messages", async ({ request }) => {
        ids.push((await request.json() as { request_id: string }).request_id);
        return HttpResponse.error();
      }),
    );
    render(<AgentChatPage />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.queryByText("正在读取对话…")).not.toBeInTheDocument());
    await user.type(screen.getByLabelText("发送消息"), "重试问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await user.click(await screen.findByRole("button", { name: "重试" }));
    await waitFor(() => expect(ids).toHaveLength(2));
    expect(ids[0]).not.toBe(ids[1]);
  });
  it("discards a submission response arriving after reset", async () => {
    let release!: () => void;
    const barrier = new Promise<void>((resolve) => { release = resolve; });
    let entered!: () => void;
    const started = new Promise<void>((resolve) => { entered = resolve; });
    server.use(
      http.post("/api/agent/1/messages", async () => { entered(); await barrier; return HttpResponse.json(run); }),
      http.post("/api/agent/1/conversation/reset", () => HttpResponse.json({ generation: 1, messages: [], run: null })),
    );
    render(<AgentChatPage />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.queryByText("正在读取对话…")).not.toBeInTheDocument());
    await user.type(screen.getByLabelText("发送消息"), "旧问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await started;
    await user.click(screen.getByRole("button", { name: "重置对话" }));
    await waitFor(() => expect(screen.getByLabelText("发送消息")).toHaveValue(""));
    await act(async () => { release(); await barrier; });
    expect(screen.queryByText("正在生成回答…")).not.toBeInTheDocument();
    expect(EventStream.streams).toHaveLength(0);
  });

  it("reuses request identity when a submission response is lost", async () => {
    const submitted: { request_id: string }[] = [];
    server.use(http.post("/api/agent/1/messages", async ({ request }) => {
      submitted.push(await request.json() as { request_id: string });
      return HttpResponse.error();
    }));
    render(<AgentChatPage />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.queryByText("正在读取对话…")).not.toBeInTheDocument());
    await user.type(screen.getByLabelText("发送消息"), "只运行一次");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(submitted).toHaveLength(2));
    expect(submitted[0].request_id).toBeTruthy();
    expect(submitted[0]).toEqual(submitted[1]);
  });
  it("stops and resets through public endpoints and ignores queued old events", async () => {
    let reset = false;
    server.use(
      http.get("/api/agent/1/conversation", () => HttpResponse.json({
        generation: reset ? 1 : 0, messages: [], run: reset ? null : run,
      })),
      http.post("/api/agent/1/runs/run-1/stop", () => HttpResponse.json({ ...run, status: "failed", error_code: "cancelled" })),
      http.post("/api/agent/1/conversation/reset", () => {
        reset = true;
        return HttpResponse.json({ generation: 1, messages: [], run: null });
      }),
    );
    render(<AgentChatPage />);
    const user = userEvent.setup();
    await screen.findByText("正在生成回答…");
    await waitFor(() => expect(EventStream.streams).toHaveLength(1));
    const old = EventStream.streams[0];
    await user.click(screen.getByRole("button", { name: "停止生成" }));
    await screen.findByText(/已停止/);
    act(() => old.emit("delta", { text: "停止后的旧内容" }));
    expect(screen.queryByText("停止后的旧内容")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重置对话" }));
    await waitFor(() => expect(screen.queryByText(/已停止/)).not.toBeInTheDocument());
    act(() => old.emit("completed", { status: "completed" }));
    expect(screen.queryByText("回答已完成并保存")).not.toBeInTheDocument();
    expect(old.closed).toBe(true);
  });
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
    act(() => old.emit("tool", { name: "read_skill", status: "completed" }));
    expect(screen.getByText("已读取经营分析技能")).toBeInTheDocument();
    storeId = 2;
    page.rerender(<AgentChatPage />);
    await waitFor(() => expect(screen.queryByText("正在读取对话…")).not.toBeInTheDocument());
    act(() => old.emit("delta", { text: "门店1的迟到内容" }));
    act(() => old.emit("tool", { name: "store_overview", status: "completed" }));
    expect(old.closed).toBe(true);
    expect(screen.queryByText(/已读取经营分析技能|已查询经营概览/)).not.toBeInTheDocument();
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
