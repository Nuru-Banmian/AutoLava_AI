import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  server.use(http.get("/api/agent/:store/memory-jobs", () => HttpResponse.json({ items: [] })));
});
afterEach(() => { server.resetHandlers(); server.close(); vi.unstubAllGlobals(); });

describe("AI conversation", () => {
  it("renders saved charts inside the answer and deduplicates completed-event replay", async () => {
    const descriptor = { chart_id: "chart-1", schema_version: 1, type: "line", title: "保存的趋势", unit: "EUR", range: { start: "2026-07-01", end: "2026-07-01" }, point_count: 1 };
    let completed = false;
    let chartReads = 0;
    server.use(
      http.get("/api/agent/1/conversation", () => HttpResponse.json({ generation: 0,
        messages: [{ id: 4, role: "assistant", content: "真实保存的图表分析", charts: [descriptor, descriptor] }],
        run: completed ? { ...run, status: "completed" } : run })),
      http.get("/api/agent/1/messages/4/charts/chart-1", () => {
        chartReads++;
        return HttpResponse.json({ chart_id: "chart-1", message_id: 4, schema_version: 1, source: {}, created_at: "2026-10-10",
          payload: { ...descriptor, dimension: "day", granularity: "day", queried_at: "2026-10-10", unfinished: false, coverage: {}, notes: [],
            series: [{ key: "total_revenue", label: "营业额" }], points: [{ dimension: "2026-07-01", state: "营业", values: { total_revenue: { exact: "19", plot: 19, status: "available" } } }] } });
      }),
    );
    render(<AgentChatPage />);
    const answer = (await screen.findByText("真实保存的图表分析")).closest("article")!;
    expect(await within(answer).findByLabelText("保存的趋势查看日期")).toBeVisible();
    expect(screen.getAllByRole("figure", { name: "保存的趋势" })).toHaveLength(1);
    await waitFor(() => expect(EventStream.streams).toHaveLength(1));
    act(() => EventStream.streams[0].emit("tool", { name: "store_chart", status: "completed" }));
    expect(screen.getByText("已准备图表，完成后保存")).toBeVisible();
    completed = true;
    act(() => EventStream.streams[0].emit("completed", { message_id: 4, charts: [descriptor] }));
    await waitFor(() => expect(EventStream.streams[0].closed).toBe(true));
    expect(screen.getAllByRole("figure", { name: "保存的趋势" })).toHaveLength(1);
    expect(chartReads).toBe(1);
    expect(screen.queryByText("已准备图表，完成后保存")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "AI对话" })).not.toBeInTheDocument();
  });

  it("fills editable questions without sending and preserves an existing draft", async () => {
    const submitted: { content: string }[] = [];
    server.use(http.post("/api/agent/1/messages", async ({ request }) => {
      submitted.push(await request.json() as { content: string });
      return HttpResponse.json(run);
    }));
    render(<AgentChatPage />);
    const user = userEvent.setup();
    const question = await screen.findByRole("button", { name: "本月经营概览" });
    await waitFor(() => expect(question).toBeEnabled());
    expect(within(screen.getByRole("region", { name: "固定提问" })).getAllByRole("button")).toHaveLength(6);
    await user.type(screen.getByLabelText("发送消息"), "先保留我的要求");
    await user.click(question);
    const input = screen.getByLabelText("发送消息");
    expect(input).toHaveFocus();
    expect((input as HTMLTextAreaElement).value).toMatch(/^先保留我的要求\n\n请概括当前门店/);
    expect(submitted).toHaveLength(0);
    await user.type(input, "补充说明");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].content).toContain("补充说明");
  });

  it("keeps preset examples separate from saved history and available after reset", async () => {
    let reset = false;
    server.use(
      http.get("/api/agent/1/conversation", () => HttpResponse.json({ generation: 0,
        messages: reset ? [] : [{ id: 1, role: "assistant", content: "真实保存的历史" }], run: null })),
      http.post("/api/agent/1/conversation/reset", () => {
        reset = true;
        return HttpResponse.json({ generation: 1, messages: [], run: null });
      }),
    );
    const page = render(<AgentChatPage />);
    await screen.findByText("真实保存的历史");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "示例会话" }));
    const examples = screen.getByRole("region", { name: "示例会话" });
    expect(examples).toHaveTextContent("预设演示问答，不是实际查询记录");
    expect(examples).not.toHaveTextContent("真实保存的历史");
    await user.click(screen.getByText("未统计与集中清点解释", { selector: "summary" }));
    expect(within(examples).getByText("未统计是不是零营业额？")).toBeVisible();
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "重置对话" }));
    await waitFor(() => expect(screen.queryByText("真实保存的历史")).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "示例会话" }));
    expect(screen.getByRole("region", { name: "示例会话" })).toHaveTextContent("未统计是不是零营业额？");
    page.unmount();
    render(<AgentChatPage />);
    await user.click(screen.getByRole("button", { name: "示例会话" }));
    expect(screen.getByRole("region", { name: "示例会话" })).toBeVisible();
  });

  it("opens the chosen example without changing drafts or saved history and restores input focus", async () => {
    render(<AgentChatPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("发送消息"), "我的问题草稿");
    await user.click(screen.getByRole("button", { name: /示例 03/ }));
    const dialog = screen.getByRole("dialog", { name: "示例会话" });
    expect(within(dialog).getByText("未统计是不是零营业额？")).toBeVisible();
    expect(within(dialog).getByText("每日台账与公司结算有什么区别？")).not.toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("发送消息")).toHaveValue("我的问题草稿");
    expect(screen.getByLabelText("发送消息")).toHaveFocus();
  });

  it("does not truncate long drafts and clears selected prompts when switching stores", async () => {
    const page = render(<AgentChatPage />);
    const question = await screen.findByRole("button", { name: "每日收入折线图" });
    await waitFor(() => expect(question).toBeEnabled());
    fireEvent.change(screen.getByLabelText("发送消息"), { target: { value: "长".repeat(5999) } });
    await userEvent.setup().click(question);
    expect(screen.getByLabelText("发送消息")).toHaveValue("长".repeat(5999));
    expect(screen.getByRole("alert")).toHaveTextContent("超过 6,000 字");
    storeId = 2;
    page.rerender(<AgentChatPage />);
    expect(screen.getByLabelText("发送消息")).toHaveValue("");
  });

  it("disables fixed questions while a response is running", async () => {
    server.use(http.get("/api/agent/1/conversation", () => HttpResponse.json({ messages: [], run })));
    render(<AgentChatPage />);
    await screen.findByText("正在生成回答…");
    for (const button of within(screen.getByRole("region", { name: "固定提问" })).getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
  });

  it("renders assistant Markdown and keeps user messages as the original text", async () => {
    server.use(http.get("/api/agent/1/conversation", () => HttpResponse.json({
      messages: [
        { id: 1, role: "user", content: "**请分析**\n第二行" },
        { id: 2, role: "assistant", content: "## 经营摘要\n\n**营业额**增长。\n\n- 检查经营日\n- 对比上周\n\n| 指标 | 数值 |\n| --- | --- |\n| 营业额 | 100 |\n\n```python\nprint('你好')\n```\n\n[参考资料](https://example.com/report)" },
      ], run: null,
    })));
    render(<AgentChatPage />);
    expect(await screen.findByRole("heading", { name: "经营摘要" })).toBeVisible();
    expect(screen.getByText("营业额", { selector: "strong" })).toBeVisible();
    expect(screen.getByRole("table")).toHaveTextContent("营业额100");
    expect(screen.getByText("print('你好')", { selector: "code" })).toBeVisible();
    expect(screen.getByRole("link", { name: "参考资料" })).toHaveAttribute("rel", "noopener noreferrer");
    const message = screen.getByRole("article", { name: "你的消息" });
    expect(message).toHaveTextContent("**请分析**");
    expect(message.querySelector("strong")).toBeNull();
    expect(within(screen.getByRole("region", { name: "聊天记录" })).getByRole("heading", { name: "经营摘要" })).toBeVisible();
  });

  it("blocks raw HTML and unsafe links without fetching remote Markdown images", async () => {
    server.use(http.get("/api/agent/1/conversation", () => HttpResponse.json({
      messages: [{ id: 1, role: "assistant", content: "[危险链接](javascript:alert%281%29)\n\n[危险数据](data:text/html,bad)\n\n<script>alert('bad')</script>\n\n<iframe src='https://example.com/embed'></iframe>\n\n![示意图](https://example.com/image.png)\n\n安全内容" }], run: null,
    })));
    render(<AgentChatPage />);
    await screen.findByText("安全内容");
    expect(screen.queryByRole("link", { name: "危险链接" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "危险数据" })).not.toBeInTheDocument();
    const message = screen.getByRole("article", { name: "AI 助手的消息" });
    expect(message.querySelector("script, iframe, img")).toBeNull();
    expect(screen.getByRole("link", { name: "图片：示意图" })).toHaveAttribute("href", "https://example.com/image.png");
  });

  it("renders Markdown while streaming and preserves failed output for review", async () => {
    server.use(http.get("/api/agent/1/conversation", () => HttpResponse.json({ messages: [], run })));
    render(<AgentChatPage />);
    await waitFor(() => expect(EventStream.streams).toHaveLength(1));
    act(() => EventStream.streams[0].emit("delta", { text: "## 实时结论\n\n**正在整理**" }));
    expect(screen.getByRole("heading", { name: "实时结论" })).toBeVisible();
    expect(screen.getByText("正在整理", { selector: "strong" })).toBeVisible();
    act(() => EventStream.streams[0].emit("failed", { error_code: "model_timeout" }));
    expect(screen.getByRole("alert")).toHaveTextContent("模型响应超时");
    expect(screen.getByRole("heading", { name: "实时结论" })).toBeVisible();
    expect(screen.queryByText("回答已完成并保存")).not.toBeInTheDocument();
  });

  it("explains invalid memory proposals and keeps the original failure record", async () => {
    server.use(
      http.get("/api/agent/1/memories", () => HttpResponse.json({ items: [], next_before: null })),
      http.get("/api/agent/1/memory-jobs", () => HttpResponse.json({ items: [{ id: 1, message_id: 2,
        status: "failed", attempts: 3, calls: 3, error_code: "memory_invalid_proposal",
        failures: [{ code: "memory_invalid_proposal" }], created_at: "2026-10-08T01:00:00" }], next_before: null })),
    );
    render(<AgentChatPage />);
    await userEvent.setup().click(screen.getByRole("button", { name: "查看记忆" }));
    expect(await screen.findByText("最新：整理失败")).toBeVisible();
    expect(screen.getAllByText(/整理结果格式不符合要求，本次未保存/)[0]).toBeVisible();
    await userEvent.setup().click(screen.getByText(/查看整理记录/));
    expect(screen.getByText(/失败记录：memory_invalid_proposal/)).toBeVisible();
  });

  it("sends on Enter, preserves Shift+Enter newlines, and waits for Chinese composition", async () => {
    const submitted: { content: string }[] = [];
    server.use(http.post("/api/agent/1/messages", async ({ request }) => {
      submitted.push(await request.json() as { content: string });
      return HttpResponse.json(run, { status: 202 });
    }));
    render(<AgentChatPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "重置对话" })).toBeEnabled());
    const user = userEvent.setup();
    const input = screen.getByLabelText("发送消息");
    await user.type(input, "第一行{shift>}{enter}{/shift}第二行");
    expect(input).toHaveValue("第一行\n第二行");
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", isComposing: true });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 229 });
    expect(submitted).toHaveLength(0);
    await user.keyboard("{Enter}");
    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].content).toBe("第一行\n第二行");
  });

  it("reads saved memory evidence after reset and discards a late old-store list", async () => {
    let release!: () => void;
    const barrier = new Promise<void>((resolve) => { release = resolve; });
    const memory = { id: "memory-1", content: "先给结论，再列数据", category: "preference",
      status: "active", version: 1, index_status: "pending", updated_at: "2026-10-08T01:00:00",
      sources: [{ run_id: "source-run", message_id: 3, evidence: "先给结论，再列数据", created_at: "2026-10-08T01:00:00" }] };
    let delay = false;
    server.use(
      http.get("/api/agent/1/memories", async () => {
        if (delay) await barrier;
        return HttpResponse.json({ items: [memory], next_before: null });
      }),
      http.get("/api/agent/2/memories", () => HttpResponse.json({ items: [], next_before: null })),
      http.post("/api/agent/1/conversation/reset", () => HttpResponse.json({ generation: 1, messages: [], run: null })),
    );
    const user = userEvent.setup();
    const view = render(<AgentChatPage />);
    await user.click(screen.getByRole("button", { name: "查看记忆" }));
    await screen.findByText("先给结论，再列数据", { selector: "p" });
    await user.click(screen.getByText("查看来源"));
    expect(screen.getByText(/来源消息 #3/)).toBeVisible();
    expect(screen.getByText(/索引待处理，向量检索尚未就绪/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重置对话" }));
    expect(screen.getByText(/来源消息 #3/)).toBeVisible();
    delay = true;
    await user.click(screen.getByRole("button", { name: "刷新记忆" }));
    storeId = 2;
    view.rerender(<AgentChatPage />);
    await user.click(screen.getByRole("button", { name: "查看记忆" }));
    await screen.findByText("当前管理员在此门店暂无记忆。");
    await act(async () => { release(); await barrier; });
    expect(screen.queryByText(/来源消息 #3/)).not.toBeInTheDocument();
  });
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
  it("explains pagination partial results and context capacity through tool events", async () => {
    server.use(http.get("/api/agent/1/conversation", () => HttpResponse.json({
      generation: 0, messages: [], run,
    })));
    render(<AgentChatPage />);
    await waitFor(() => expect(EventStream.streams).toHaveLength(1));
    const stream = EventStream.streams[0];
    act(() => stream.emit("tool", {
      name: "store_query", status: "partial", message: "已读取当前页 2 行，剩余结果尚未读取。",
    }));
    expect(screen.getByText("查询部分完成：已读取当前页 2 行，剩余结果尚未读取。")).toBeVisible();
    act(() => stream.emit("tool", {
      name: "store_query", status: "partial",
      message: "上下文容量不足，剩余结果未读取，请缩小查询范围。",
      failures: [{ code: "context_capacity" }],
    }));
    expect(screen.getByText("查询部分完成：上下文容量不足，剩余结果未读取，请缩小查询范围。")).toBeVisible();
    expect(screen.queryByText("本次工具请求未获执行")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("keeps the saved pagination partial answer after completion and a fresh page read", async () => {
    const question = "请查询所有经营记录";
    const answer = "部分完成：本轮仅读取 2 / 8 行，剩余 6 行未读取。请缩小查询范围后继续。";
    let submissions = 0;
    let completed = false;
    server.use(
      http.get("/api/agent/1/conversation", () => HttpResponse.json({
        generation: 0,
        messages: submissions ? [
          { id: 1, role: "user", content: question },
          ...(completed ? [{ id: 2, role: "assistant", content: answer }] : []),
        ] : [],
        run: submissions ? { ...run, status: completed ? "completed" : "running", output: completed ? answer : "" } : null,
      })),
      http.post("/api/agent/1/messages", () => { submissions++; return HttpResponse.json(run, { status: 202 }); }),
    );
    const view = render(<AgentChatPage />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("button", { name: "重置对话" })).toBeEnabled());
    await user.type(screen.getByLabelText("发送消息"), question);
    await user.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(EventStream.streams).toHaveLength(1));
    act(() => EventStream.streams[0].emit("delta", { text: answer }));
    expect(screen.getByText(answer)).toBeVisible();
    completed = true;
    act(() => EventStream.streams[0].emit("completed", { status: "completed" }));
    await screen.findByText("回答已完成并保存");
    expect(screen.getByText(answer)).toBeVisible();
    view.unmount();
    render(<AgentChatPage />);
    expect(await screen.findByText(answer)).toBeVisible();
    expect(screen.getByText("回答已完成并保存")).toBeVisible();
    expect(screen.queryByText("正在生成回答…")).not.toBeInTheDocument();
    expect(EventStream.streams).toHaveLength(1);
    expect(EventStream.streams[0].closed).toBe(true);
    expect(submissions).toBe(1);
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
