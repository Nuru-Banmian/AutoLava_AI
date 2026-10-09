import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { AgentChart } from "./AgentChart";
import { advanceSessionScope } from "@/auth/sessionScope";

const description = { chart_id: "chart-1", schema_version: 1 as const, type: "line" as const,
  title: "日趋势", unit: "EUR", range: { start: "2026-07-01", end: "2026-07-03" }, point_count: 3 };
const snapshot = { ...description, message_id: 4, created_at: "2026-10-09", source: {}, payload: {
  ...description, dimension: "day", granularity: "day", queried_at: "2026-10-09", unfinished: true, coverage: { interval_days: 3 }, notes: [],
  series: [{ key: "total_revenue", label: "营业额" }], points: [
    { dimension: "2026-07-01", state: "营业", values: { total_revenue: { exact: "19.12", plot: 19.12, status: "available" } } },
    { dimension: "2026-07-02", state: "营业", values: { total_revenue: { exact: "0", plot: 0, status: "available" } } },
    { dimension: "2026-07-03", state: "未统计", values: { total_revenue: { exact: null, plot: null, status: "no_statistical_ledger" } } },
  ],
} };
const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { server.resetHandlers(); server.close(); });

it("reads a saved snapshot and selects exact decimals, real zero and unknown states", async () => {
  server.use(http.get("/api/agent/1/messages/4/charts/chart-1", () => HttpResponse.json(snapshot)));
  const user = userEvent.setup();
  render(<AgentChart storeId={1} messageId={4} description={description} />);
  const select = await screen.findByLabelText("日趋势查看日期");
  expect(screen.getByText("当前周期尚未结束，仅统计至查询日。")).toBeVisible();
  const data = within(screen.getByRole("status", { name: "图表数据" }));
  await user.selectOptions(select, "0");
  expect(data.getByText(/营业额：19.12 EUR/)).toBeVisible();
  await user.selectOptions(select, "1");
  expect(data.getByText(/营业额：0 EUR/)).toBeVisible();
  await user.selectOptions(select, "2");
  expect(data.getByText(/2026-07-03 · 未统计/)).toBeVisible();
  expect(data.getByText(/营业额：未知/)).toBeVisible();
  expect(screen.queryByRole("button", { name: /下载/ })).not.toBeInTheDocument();
});

it("retries a failed fetch without reporting missing data", async () => {
  let reads = 0;
  server.use(http.get("/api/agent/1/messages/4/charts/chart-1", () => ++reads === 1
    ? HttpResponse.json({ detail: "暂不可用" }, { status: 503 }) : HttpResponse.json(snapshot)));
  render(<AgentChart storeId={1} messageId={4} description={description} />);
  await userEvent.click(await screen.findByRole("button", { name: "重试图表" }));
  expect(await screen.findByLabelText("日趋势查看日期")).toBeVisible();
  expect(reads).toBe(2);
});

it("drops late responses after store or session scope changes", async () => {
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => { release = resolve; });
  server.use(http.get("/api/agent/1/messages/4/charts/chart-1", async () => { await barrier; return HttpResponse.json(snapshot); }));
  server.use(http.get("/api/agent/2/messages/4/charts/chart-1", () => HttpResponse.json({ detail: "没有此图表" }, { status: 404 })));
  const view = render(<AgentChart storeId={1} messageId={4} description={description} />);
  advanceSessionScope();
  view.rerender(<AgentChart storeId={2} messageId={4} description={description} />);
  await screen.findByRole("alert");
  await act(async () => { release(); await barrier; });
  expect(screen.queryByLabelText("日趋势查看日期")).not.toBeInTheDocument();
});
