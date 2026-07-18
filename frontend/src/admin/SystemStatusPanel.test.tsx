import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { SystemStatusPanel } from "@/admin/SystemStatusPanel";

vi.mock("@/stores/StoreProvider", () => ({
  useStore: () => ({ selected: { id: 1, name: "Roma", timezone: "Europe/Rome" } }),
}));

const server = setupServer();
const dashboard = [{
  card_type: "today",
  state: "recorded",
  revenue: "100.00",
  weather: "晴",
  weekday: null,
  temperature_max: null,
  temperature_min: null,
  precipitation: null,
  hint: null,
  generated_at: "2026-07-16T08:30:00Z",
  timestamp_status: "utc",
}];
const weatherTask = [{
  id: 1,
  store_id: 1,
  task_type: "weather_refresh",
  status: "success",
  message: null,
  retry_count: 0,
  started_at: "2026-07-16T08:00:00Z",
  finished_at: "2026-07-16T08:05:00Z",
  created_at: "2026-07-16T08:00:00Z",
  timestamp_status: "utc",
}];

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function mockStatus({
  alerts = [],
  taskLogs = weatherTask,
  stores = [{ id: 1, name: "Roma", address: "Roma", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true }],
  cardsByStore = { 1: dashboard },
}: {
  alerts?: unknown[];
  taskLogs?: unknown[];
  stores?: unknown[];
  cardsByStore?: Record<number, unknown[]>;
} = {}) {
  server.use(
    http.get("/api/admin/stores", () => HttpResponse.json(stores)),
    http.get("/api/admin/alerts", () => HttpResponse.json(alerts)),
    http.get("/api/admin/task-logs", () => HttpResponse.json(taskLogs)),
    http.get("/api/dashboard/:storeId", ({ params }) => HttpResponse.json(cardsByStore[Number(params.storeId)] ?? [])),
  );
}

function renderStatus() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><SystemStatusPanel /></QueryClientProvider>);
}

describe("SystemStatusPanel", () => {
  it("reports loading without claiming a healthy state", () => {
    mockStatus();
    renderStatus();
    expect(screen.getByRole("status")).toHaveTextContent("正在获取系统状态");
    expect(screen.queryByText("运行正常")).not.toBeInTheDocument();
  });

  it.each(["/api/admin/stores", "/api/admin/alerts", "/api/admin/task-logs", "/api/dashboard/1"])("does not claim healthy when required request %s fails", async (endpoint) => {
    mockStatus();
    server.use(http.get(endpoint, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
    renderStatus();
    expect(await screen.findByRole("alert")).toHaveTextContent("状态暂时无法获取");
    expect(screen.queryByText("运行正常")).not.toBeInTheDocument();
  });

  it("distinguishes empty and partial status data", async () => {
    mockStatus({ stores: [], taskLogs: [], cardsByStore: {} });
    const empty = renderStatus();
    expect(await screen.findByText("暂无可用状态数据")).toBeInTheDocument();
    expect(screen.queryByText("运行正常")).not.toBeInTheDocument();
    empty.unmount();

    mockStatus({ taskLogs: [] });
    renderStatus();
    expect(await screen.findByText("状态数据不完整")).toBeInTheDocument();
    expect(screen.getByText(/最近仪表盘生成/)).toBeInTheDocument();
    expect(screen.getByText("暂无记录")).toBeInTheDocument();
    expect(screen.queryByText("运行正常")).not.toBeInTheDocument();
  });

  it("shows unresolved alerts and blocks healthy state for error-level alerts", async () => {
    mockStatus({ alerts: [{
      id: 8,
      store_id: 1,
      alert_type: "weather",
      level: "error",
      message: "天气同步失败",
      is_resolved: false,
      created_at: "2026-07-16T08:10:00Z",
      resolved_at: null,
      timestamp_status: "utc",
    }] });
    renderStatus();
    expect(await screen.findByText("系统存在未解决错误")).toBeInTheDocument();
    expect(screen.getByText(/天气同步失败/)).toBeInTheDocument();
    expect(screen.getByText("未解决告警（1）")).toBeInTheDocument();
    expect(screen.queryByText("运行正常")).not.toBeInTheDocument();
  });

  it("claims healthy only with complete successful data and no unresolved error", async () => {
    mockStatus({ alerts: [{
      id: 9,
      store_id: null,
      alert_type: "reminder",
      level: "warning",
      message: "一条提醒",
      is_resolved: false,
      created_at: "2026-07-16T08:15:00Z",
      resolved_at: null,
      timestamp_status: "utc",
    }] });
    renderStatus();
    expect(await screen.findByText("运行正常")).toBeInTheDocument();
    expect(screen.getByText(/最近天气更新/)).toBeInTheDocument();
    expect(screen.getByText(/最近仪表盘生成/)).toBeInTheDocument();
    expect(screen.getByText(/一条提醒/)).toBeInTheDocument();
  });

  it("keeps named status cards in the desktop hierarchy", async () => {
    mockStatus();
    renderStatus();

    await screen.findByText("运行正常");
    const summary = screen.getByRole("region", { name: "运行状态" });
    const unresolvedAlerts = screen.getByRole("region", { name: /未解决告警/ });

    expect(summary.parentElement).toHaveClass("grid", "gap-4", "lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.7fr)]");
    expect(summary).toHaveClass("space-y-3", "rounded-xl", "border", "bg-card", "p-5", "shadow-sm");
    expect(unresolvedAlerts).toHaveClass("space-y-3", "rounded-xl", "border", "bg-card", "p-5", "shadow-sm");
  });

  it("reports the production weather refresh task when its latest run failed", async () => {
    mockStatus({ taskLogs: [{ ...weatherTask[0], status: "failed", message: "天气刷新完成：共 2 个门店，成功 1 个，失败 1 个" }] });
    renderStatus();
    expect(await screen.findByRole("alert")).toHaveTextContent("最近天气任务未成功");
    expect(screen.queryByText("运行正常")).not.toBeInTheDocument();
  });

  it("does not let a newer weather backfill hide a failed weather refresh", async () => {
    mockStatus({ taskLogs: [
      { ...weatherTask[0], status: "failed", finished_at: "2026-07-16T08:05:00Z" },
      { ...weatherTask[0], id: 2, task_type: "weather_backfill", status: "success", finished_at: "2026-07-16T09:05:00Z" },
    ] });
    renderStatus();

    expect(await screen.findByRole("alert")).toHaveTextContent("最近天气任务未成功");
    expect(screen.queryByText("运行正常")).not.toBeInTheDocument();
    expect(screen.getByText(/最近天气更新/).parentElement).toHaveTextContent(/08:05/);
  });

  it("keeps store-to-dashboard completeness and treats one empty store as partial", async () => {
    const stores = [
      { id: 1, name: "Roma", address: "Roma", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true },
      { id: 2, name: "Milano", address: "Milano", latitude: "45.4", longitude: "9.2", timezone: "Europe/Rome", is_active: true },
    ];
    mockStatus({ stores, cardsByStore: { 1: dashboard, 2: [] } });
    renderStatus();
    expect(await screen.findByText("状态数据不完整")).toBeInTheDocument();
    expect(screen.getByText(/Roma/)).toBeInTheDocument();
    expect(screen.getByText(/Milano/)).toHaveTextContent("暂无记录");
    expect(screen.queryByText("运行正常")).not.toBeInTheDocument();
  });

  it("claims healthy when every active store has a valid generated timestamp", async () => {
    const stores = [
      { id: 1, name: "Roma", address: "Roma", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true },
      { id: 2, name: "Milano", address: "Milano", latitude: "45.4", longitude: "9.2", timezone: "Europe/Rome", is_active: true },
    ];
    mockStatus({ stores, cardsByStore: { 1: dashboard, 2: [{ ...dashboard[0], generated_at: "2026-07-16T09:00:00Z" }] } });
    renderStatus();
    expect(await screen.findByText("运行正常")).toBeInTheDocument();
    expect(screen.getByText(/Roma/)).toBeInTheDocument();
    expect(screen.getByText(/Milano/)).toBeInTheDocument();
  });

  it("orders timestamps by epoch across offsets and labels UTC explicitly", async () => {
    mockStatus({ taskLogs: [
      { ...weatherTask[0], id: 1, finished_at: "2026-07-16T10:00:00+02:00" },
      { ...weatherTask[0], id: 2, finished_at: "2026-07-16T09:30:00Z" },
    ] });
    renderStatus();
    expect(await screen.findByText("运行正常")).toBeInTheDocument();
    expect(screen.getByText(/最近天气更新/).parentElement).toHaveTextContent(/UTC.*09:30/);
  });

  it("rejects naive timestamps instead of guessing their timezone", async () => {
    mockStatus({
      taskLogs: [{ ...weatherTask[0], finished_at: "2026-07-16T09:30:00" }],
      cardsByStore: { 1: [{ ...dashboard[0], generated_at: "2026-07-16T08:30:00" }] },
    });
    renderStatus();
    expect(await screen.findByText("状态数据不完整")).toBeInTheDocument();
    expect(screen.getAllByText("时间格式缺少时区").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("运行正常")).not.toBeInTheDocument();
  });

  it("blocks healthy when valid and legacy-unknown required timestamps are mixed", async () => {
    mockStatus({
      taskLogs: [weatherTask[0], { ...weatherTask[0], id: 2, timestamp_status: "legacy_unknown", started_at: null, finished_at: null, created_at: null }],
      cardsByStore: { 1: [dashboard[0], { ...dashboard[0], card_type: "tomorrow", timestamp_status: "legacy_unknown", generated_at: null }] },
    });
    renderStatus();
    expect(await screen.findByText("状态数据不完整")).toBeInTheDocument();
    expect(screen.getAllByText(/历史时间时区未知/).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("运行正常")).not.toBeInTheDocument();
  });
});
