import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { AgentMemoryPanel } from "./AgentMemoryPanel";

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { server.resetHandlers(); server.close(); });

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
