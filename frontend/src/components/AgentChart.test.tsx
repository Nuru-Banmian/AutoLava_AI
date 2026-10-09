import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { AgentChart } from "./AgentChart";
import { advanceSessionScope } from "@/auth/sessionScope";
import { AgentChartCache } from "./AgentChartCache";

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

it("loads only near the viewport and draws only while visible with stable space", async () => {
  const observers: { callback: IntersectionObserverCallback; options?: IntersectionObserverInit }[] = [];
  vi.stubGlobal("IntersectionObserver", class {
    constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) { observers.push({ callback, options }); }
    observe() {} disconnect() {}
  });
  let reads = 0;
  server.use(http.get("/api/agent/1/messages/4/charts/chart-1", () => { reads++; return HttpResponse.json(snapshot); }));
  const view = render(<AgentChart storeId={1} messageId={4} description={description} />);
  try {
    expect(reads).toBe(0);
    expect(screen.queryByLabelText("日趋势查看日期")).not.toBeInTheDocument();
    const near = observers.find(o => o.options?.rootMargin);
    const visible = observers.find(o => !o.options?.rootMargin);
    expect(near).toBeDefined(); expect(visible).toBeDefined();
    await act(async () => near!.callback([{ isIntersecting: true }] as IntersectionObserverEntry[], {} as IntersectionObserver));
    await screen.findByText(/图表已读取/);
    expect(reads).toBe(1);
    expect(screen.queryByLabelText("日趋势查看日期")).not.toBeInTheDocument();
    await act(async () => visible!.callback([{ isIntersecting: true }] as IntersectionObserverEntry[], {} as IntersectionObserver));
    expect(await screen.findByLabelText("日趋势查看日期")).toBeVisible();
    await act(async () => visible!.callback([{ isIntersecting: false }] as IntersectionObserverEntry[], {} as IntersectionObserver));
    expect(screen.queryByLabelText("日趋势查看日期")).not.toBeInTheDocument();
  } finally { view.unmount(); vi.unstubAllGlobals(); }
});

it.each(["grouped_bar", "stacked_bar", "horizontal_bar"] as const)("renders %s with exact selection and segment context", async (type) => {
  const changed = { ...snapshot, payload: { ...snapshot.payload, type, y_domain: [0, 100],
    segment: { index: 1, count: 2, total_range: { start: "2026-01-01", end: "2026-12-31" } } } };
  server.use(http.get("/api/agent/1/messages/4/charts/chart-1", () => HttpResponse.json(changed)));
  const view = render(<AgentChart storeId={1} messageId={4} description={{ ...description, type }} />);
  const select = await screen.findByLabelText("日趋势查看日期");
  expect(screen.getByText(/总范围：2026-01-01 至 2026-12-31 · 第 1\/2 段/)).toBeVisible();
  expect(view.container.querySelector(".recharts-bar")).not.toBeNull();
  await userEvent.selectOptions(select, "1");
  expect(within(screen.getByRole("status", { name: "图表数据" })).getByText(/营业额：0 EUR/)).toBeVisible();
});

it("deduplicates a shared chart and invalidates cached data on generation reset", async () => {
  let reads = 0;
  server.use(http.get("/api/agent/1/messages/4/charts/chart-1", () => { reads++; return HttpResponse.json(snapshot); }));
  const charts = <><AgentChart storeId={1} messageId={4} description={description} /><AgentChart storeId={1} messageId={4} description={description} /></>;
  const view = render(<AgentChartCache key="generation-0">{charts}</AgentChartCache>);
  expect(await screen.findAllByLabelText("日趋势查看日期")).toHaveLength(2);
  expect(reads).toBe(1);
  view.rerender(<AgentChartCache key="generation-0">{charts}</AgentChartCache>);
  expect(reads).toBe(1);
  view.rerender(<AgentChartCache key="generation-1">{charts}</AgentChartCache>);
  expect(await screen.findAllByLabelText("日趋势查看日期")).toHaveLength(2);
  expect(reads).toBe(2);
});

it.each(["reset", "unmount"])("aborts and discards a delayed chart after %s", async action => {
  let release!: () => void;
  const barrier = new Promise<void>(resolve => { release = resolve; });
  let started!: () => void;
  const requested = new Promise<void>(resolve => { started = resolve; });
  let aborted = false;
  server.use(http.get("/api/agent/1/messages/4/charts/chart-1", async ({ request }) => {
    request.signal.addEventListener("abort", () => { aborted = true; }); started();
    await barrier; return HttpResponse.json(snapshot);
  }));
  const view = render(<AgentChartCache key="generation-0"><AgentChart storeId={1} messageId={4} description={description} /></AgentChartCache>);
  await requested;
  if (action === "reset") view.rerender(<AgentChartCache key="generation-1"><p>重置后没有历史图</p></AgentChartCache>);
  else view.unmount();
  await act(async () => { release(); await barrier; });
  expect(aborted).toBe(true);
  expect(screen.queryByLabelText("日趋势查看日期")).not.toBeInTheDocument();
});
