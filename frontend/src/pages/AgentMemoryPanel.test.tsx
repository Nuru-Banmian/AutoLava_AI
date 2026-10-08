import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { AgentMemoryPanel } from "./AgentMemoryPanel";

const server = setupServer();
beforeEach(() => {
  server.use(http.get("/api/agent/:storeId/memory-jobs", () => HttpResponse.json({ items: [] })));
  server.listen({ onUnhandledRequest: "error" });
});
afterEach(() => { server.resetHandlers(); server.close(); });

it("confirms, edits and rejects candidates and displays curation failures", async () => {
  let items = ["直接确认", "修改确认", "拒绝候选"].map((content, index) => ({
    id: `c${index}`, content, category: "preference", status: "pending_confirmation", version: 1,
    index_status: "not_scheduled", updated_at: "2026-10-08T01:00:00", sources: [], changes: [],
  }));
  const decisions: unknown[] = [];
  server.use(
    http.get("/api/agent/1/memories", () => HttpResponse.json({ items, revision: 3 })),
    http.get("/api/agent/1/memory-jobs", () => HttpResponse.json({ items: [{ id: 1, message_id: 4,
      status: "failed", attempts: 1, calls: 2, error_code: "model_unavailable", failures: [{ code: "model_unavailable" }] }] })),
    http.post("/api/agent/1/memories/:id/:decision", async ({ params, request }) => {
      const payload = await request.json() as { expected_version: number; content?: string };
      decisions.push({ id: params.id, decision: params.decision, ...payload });
      items = items.filter((item) => item.id !== params.id);
      return params.decision === "reject" ? new HttpResponse(null, { status: 204 }) : HttpResponse.json({});
    }),
  );
  const user = userEvent.setup();
  render(<AgentMemoryPanel storeId={1} />);
  await user.click(screen.getByRole("button", { name: "查看记忆" }));
  await screen.findByText(/整理失败/);
  const candidate = (content: string) => screen.getByText(content).closest("article")!;
  await user.click(within(candidate("直接确认")).getByRole("button", { name: "确认" }));
  await screen.findByText("候选已确认。索引待处理。");
  await user.click(within(candidate("修改确认")).getByRole("button", { name: "修改" }));
  await user.clear(screen.getByLabelText("纠正内容"));
  await user.type(screen.getByLabelText("纠正内容"), "以后回答简短");
  await user.click(screen.getByRole("button", { name: "修改后确认" }));
  await screen.findByText("候选已确认。索引待处理。");
  await user.click(within(candidate("拒绝候选")).getByRole("button", { name: "拒绝" }));
  await screen.findByText("候选已拒绝。");
  expect(decisions).toEqual([
    { id: "c0", decision: "confirm", expected_version: 1 },
    { id: "c1", decision: "confirm", expected_version: 1, content: "以后回答简短" },
    { id: "c2", decision: "reject", expected_version: 1 },
  ]);
});

it("keeps a correction draft on conflict and requires explicit deletion and clearing", async () => {
  let item = { id: "m1", content: "原偏好", category: "preference", status: "active", version: 1,
    index_status: "pending", updated_at: "2026-10-08T01:00:00", sources: [], changes: [] };
  let items = [item];
  let conflict = true;
  let deletedVersion = 0;
  let clearedRevision = -1;
  server.use(
    http.get("/api/agent/1/memories", () => HttpResponse.json({ items, revision: item.version })),
    http.patch("/api/agent/1/memories/m1", async ({ request }) => {
      const body = await request.json() as { content: string; expected_version: number };
      if (conflict) {
        conflict = false;
        item = { ...item, content: "其他窗口的新偏好", version: 2 };
        items = [item];
        return HttpResponse.json({ detail: { message: "记忆已更新，请核对当前记录和你的输入后再保存。", current: item } }, { status: 409 });
      }
      expect(body.expected_version).toBe(2);
      item = { ...item, content: body.content, version: 3 };
      items = [item];
      return HttpResponse.json(item);
    }),
    http.delete("/api/agent/1/memories/m1", async ({ request }) => {
      deletedVersion = (await request.json() as { expected_version: number }).expected_version;
      items = [];
      return new HttpResponse(null, { status: 204 });
    }),
    http.post("/api/agent/1/memories/clear", async ({ request }) => {
      clearedRevision = (await request.json() as { expected_revision: number }).expected_revision;
      return HttpResponse.json({ items: [], revision: 4 });
    }),
  );
  const user = userEvent.setup();
  render(<AgentMemoryPanel storeId={1} />);
  await user.click(screen.getByRole("button", { name: "查看记忆" }));
  await user.click(await screen.findByRole("button", { name: "纠正" }));
  await user.clear(screen.getByLabelText("纠正内容"));
  await user.type(screen.getByLabelText("纠正内容"), "我的纠正");
  await user.click(screen.getByRole("button", { name: "保存纠正" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("记忆已更新");
  expect(screen.getByLabelText("纠正内容")).toHaveValue("我的纠正");
  expect(screen.getByText("其他窗口的新偏好")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "保存纠正" }));
  await screen.findByText("我的纠正");
  await user.click(screen.getByRole("button", { name: "删除" }));
  const confirmation = screen.getByRole("alertdialog");
  expect(deletedVersion).toBe(0);
  await user.click(within(confirmation).getByRole("button", { name: "确认删除" }));
  await screen.findByText("当前管理员在此门店暂无记忆。");
  expect(deletedVersion).toBe(3);
  await user.click(screen.getByRole("button", { name: "全部清空" }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "确认清空" }));
  await screen.findByText("记忆已全部清空。");
  expect(clearedRevision).toBe(3);
  expect(screen.getByText(/旧聊天原文可能仍可见/)).toBeVisible();
});

it("keeps the old clear precondition when memories change between list pages", async () => {
  let clearRevision = -1;
  const item = { id: "m1", content: "第一页原偏好", category: "preference", status: "active", version: 1,
    index_status: "pending", updated_at: "2026-10-08T01:00:00", sources: [], changes: [] };
  server.use(
    http.get("/api/agent/1/memories", ({ request }) => HttpResponse.json(
      new URL(request.url).searchParams.has("before")
        ? { items: [{ ...item, id: "m2", content: "版本变化后的第二页" }], next_before: null, revision: 2 }
        : { items: [item], next_before: "cursor", revision: 1 },
    )),
    http.post("/api/agent/1/memories/clear", async ({ request }) => {
      clearRevision = (await request.json() as { expected_revision: number }).expected_revision;
      return clearRevision === 1
        ? HttpResponse.json({ detail: "记忆已变化，请刷新并核对后再次清空。" }, { status: 409 })
        : HttpResponse.json({ items: [], revision: 3 });
    }),
  );
  const user = userEvent.setup();
  render(<AgentMemoryPanel storeId={1} />);
  await user.click(screen.getByRole("button", { name: "查看记忆" }));
  await user.click(await screen.findByRole("button", { name: "读取更多记忆" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("记忆已变化，请刷新后继续读取。");
  expect(screen.queryByText("版本变化后的第二页")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "全部清空" }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "确认清空" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("刷新并核对后再次清空");
  expect(clearRevision).toBe(1);
  expect(screen.getByText("第一页原偏好")).toBeVisible();
});
