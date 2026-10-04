import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { AccessibleStore, ChartsResponse, RecordSnapshot, UserRole } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { downloadBusinessRecords } from "@/lib/business-record-export";
import { BusinessRecordsPage } from "@/pages/BusinessRecordsPage";
import { useStore } from "@/stores/StoreProvider";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: vi.fn() }));
vi.mock("@/stores/StoreProvider", () => ({ useStore: vi.fn() }));
vi.mock("@/lib/business-record-export", () => ({ downloadBusinessRecords: vi.fn() }));

const server = setupServer();
const berlin: AccessibleStore = { id: 1, name: "Berlin", timezone: "Europe/Berlin", is_active: true, company_settlement_enabled: false, wash_count_enabled: true };
const paris: AccessibleStore = { id: 2, name: "Paris", timezone: "Europe/Paris", is_active: true, company_settlement_enabled: false, wash_count_enabled: true };
let selectedStore: AccessibleStore | null = berlin;
type TestInitialEntry = string | { pathname: string; state?: unknown };

const record: RecordSnapshot = {
  id: 4,
  identity: "record-4",
  revision: 1,
  store_id: 1,
  date: "2026-07-14",
  daily_revenue: 100,
  income_mode: "composed",
  wash_count: 8,
  is_open: "营业",
  weather: "晴",
  weather_legacy: false,
  weather_auto: "晴",
  weather_code: 1,
  temperature_max: "20.0",
  temperature_min: "10.0",
  precipitation: "0.0",
  activity: null,
  weather_edited: false,
  scanned: false,
  created_by: 1,
  updated_by: 1,
  created_at: "2026-07-14T00:00:00",
  updated_at: "2026-07-14T00:00:00",
  created_by_name: "admin",
  updated_by_name: "admin",
  items: [{ id: 1, category_id: 1, category_name: "现金", include_in_total: true, sort_order: 1, amount: 100, created_at: "", updated_at: "" }],
};

const chartsPayload: ChartsResponse = {
  kpis: { total_revenue: 100, record_days: 1, open_days: 1, average_revenue: 100, primary_categories: [], total_wash_count: null, wash_count_covered_days: 0, wash_count_coverage_status: "missing", average_ticket: null },
  range: { start: "2026-07-01", end: "2026-07-17", bucket: "day" },
  comparison_kpis: { start: "2026-06-01", end: "2026-06-17", total_revenue: 80, open_days: 1, average_revenue: 80 },
  income_summary: { daily_ledger_revenue: 100, confirmed_settlement_income: 0, total_income: 100, includes_settlement_income: false },
  classified_included_total: 100,
  daily: [{ date: "2026-07-14", revenue: 100 }],
  categories: [{ category_id: 1, category_name: "现金", amount: 100 }],
  income_composition: [{ category_id: 1, category_name: "现金", amount: 100 }],
  excluded_categories: [],
  monthly: [{ month: "2026-07", revenue: 100, daily_ledger_revenue: 100, confirmed_settlement_income: 0, monthly_total_income: 100 }],
  weather: [],
  weekday: [],
};

function databaseResponse(items: RecordSnapshot[], page = 1, total = items.length) {
  return {
    items,
    categories: [],
    sum_daily_revenue: items.reduce((sum, item) => sum + item.daily_revenue, 0),
    total,
    page,
    page_size: 15,
  };
}

function setRole(role: UserRole) {
  vi.mocked(useAuth).mockReturnValue({
    user: { id: role === "admin" ? 1 : 2, username: role, role, is_owner: false },
    isLoading: false,
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    isLoggingIn: false,
    isLoggingOut: false,
    logoutError: null,
  });
}

function LocationProbe() {
  const location = useLocation();
  return <div aria-label="路由状态">{location.pathname}{location.search}|{JSON.stringify(location.state)}</div>;
}

function renderPage(role: UserRole = "admin", initialEntry: TestInitialEntry = "/database") {
  setRole(role);
  vi.mocked(useStore).mockImplementation(() => ({
    stores: selectedStore ? [berlin, paris] : [],
    selected: selectedStore,
    select: vi.fn(),
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const result = render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={client}><BusinessRecordsPage /><LocationProbe /></QueryClientProvider>
    </MemoryRouter>,
  );
  return { ...result, client };
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-07-17T10:00:00Z"));
  selectedStore = berlin;
  vi.mocked(downloadBusinessRecords).mockResolvedValue();
});
afterEach(() => {
  vi.useRealTimers();
  server.resetHandlers();
  vi.clearAllMocks();
});
afterAll(() => server.close());

describe("BusinessRecordsPage", () => {
  it("opens a missing calendar date on its fifteen-date page and returns focus to that record", async () => {
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([record]))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    renderPage();
    await screen.findByText("第 1 / 2 页");
    fireEvent.click(screen.getByRole("button", { name: "经营分析" }));
    const date = await screen.findByRole("button", { name: "2026-07-01 未录入 —" });
    fireEvent.click(date);
    const detail = await screen.findByRole("region", { name: "2026-07-01 营业记录详情" });
    expect(within(detail).getByText("未录入")).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-01");
    fireEvent.click(within(detail).getByRole("button", { name: "返回记录" }));
    await screen.findByText("第 2 / 2 页");
    await waitFor(() => expect(screen.getByRole("button", { name: "2026年7月1日 星期三，未录入，—" })).toHaveFocus());
    expect(screen.getByRole("button", { name: "记录" })).toHaveAttribute("aria-pressed", "true");
  });
  it("keeps the manually chosen page after a linked date's background refresh", async () => {
    let revenue = 100;
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([{ ...record, date: "2026-07-01", daily_revenue: revenue }]))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    const view = renderPage("admin", "/database?date=2026-07-01");
    await screen.findByText("第 2 / 2 页");
    fireEvent.click(screen.getByRole("button", { name: "上一页" }));
    expect(screen.getByText("第 1 / 2 页")).toBeInTheDocument();
    revenue = 200;
    await view.client.invalidateQueries({ queryKey: ["database", "records", 1] });
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    expect(screen.getByText("第 1 / 2 页")).toBeInTheDocument();
    expect(screen.getByLabelText("路由状态")).toHaveTextContent("/database|null");
  });

  it("clears the old linked date when the user changes the record range", async () => {
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([{ ...record, date: "2026-07-01" }]))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    renderPage("admin", "/database?date=2026-07-01");
    await screen.findByText("第 2 / 2 页");
    fireEvent.click(screen.getByRole("button", { name: "自定义范围" }));
    await waitFor(() => expect(screen.getByLabelText("路由状态")).toHaveTextContent("/database|null"));
    expect(await screen.findByText("第 1 / 2 页")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "2026-07-01 营业记录详情" })).not.toBeInTheDocument();
  });

  it("keeps the chosen analysis view when a linked date's records refresh in the background", async () => {
    let revenue = 100;
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([{ ...record, daily_revenue: revenue }]))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    const view = renderPage("admin", "/database?date=2026-07-14");
    await screen.findByRole("region", { name: "2026-07-14 营业记录详情" });
    fireEvent.click(screen.getByRole("button", { name: "经营分析" }));
    revenue = 200;
    await view.client.invalidateQueries({ queryKey: ["database", "records", 1] });
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    expect(screen.getByRole("button", { name: "经营分析" })).toHaveAttribute("aria-pressed", "true");
  });

  it("retains analysis amounts after a failed refresh and offers its own retry", async () => {
    let failing = false;
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([record]))),
      http.get("/api/charts/1", () => failing
        ? HttpResponse.json({ detail: "offline" }, { status: 503 })
        : HttpResponse.json(chartsPayload)),
    );
    const view = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "经营分析" }));
    await screen.findByText("现金");
    failing = true;
    await view.client.invalidateQueries({ queryKey: ["charts", 1] });
    expect(await screen.findByText("刷新经营分析失败，当前显示上次取得的数据。")).toBeInTheDocument();
    expect(screen.getAllByText("现金").length).toBeGreaterThan(0);
    failing = false;
    fireEvent.click(screen.getByRole("button", { name: "重试经营分析" }));
    await waitFor(() => expect(screen.queryByText("刷新经营分析失败，当前显示上次取得的数据。")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "记录" }));
    expect(screen.getByRole("button", { name: "2026年7月14日 星期二，营业，€100" })).toBeInTheDocument();
  });

  it("opens a valid linked date on its fifteen-date page and returns focus to that record", async () => {
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([record]))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    window.scrollTo = vi.fn();
    renderPage("admin", "/database?date=2026-07-01");
    const detail = await screen.findByRole("region", { name: "2026-07-01 营业记录详情" });
    expect(within(detail).getByText("未录入", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("第 2 / 2 页")).toBeInTheDocument();
    fireEvent.click(within(detail).getByRole("button", { name: "返回记录" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "2026年7月1日 星期三，未录入，—" })).toHaveFocus());
  });

  it("waits for the current window before showing missing dates and retries an initial failure", async () => {
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    let requests = 0;
    server.use(
      http.get("/api/database/1/records", async () => {
        requests += 1;
        if (requests === 1) {
          await pending;
          return HttpResponse.json({ detail: "offline" }, { status: 500 });
        }
        return HttpResponse.json(databaseResponse([]));
      }),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    renderPage();
    expect(screen.getByText("正在加载记录…")).toHaveAttribute("role", "status");
    expect(screen.queryByText("未录入")).not.toBeInTheDocument();
    release();
    expect(await screen.findByText("加载记录失败，请重试。")).toBeInTheDocument();
    expect(screen.queryByText("未录入")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("button", { name: "2026年7月17日 星期五，未录入，—" })).toBeInTheDocument();
  });

  it("keeps returned records and missing dates visible when a refresh fails", async () => {
    let requests = 0;
    server.use(
      http.get("/api/database/1/records", () => {
        requests += 1;
        return requests === 1
          ? HttpResponse.json(databaseResponse([record]))
          : HttpResponse.json({ detail: "offline" }, { status: 500 });
      }),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    const view = renderPage();
    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });
    await view.client.invalidateQueries({ queryKey: ["database", "records", 1] });
    expect(await screen.findByText("刷新记录失败，当前显示上次取得的数据。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2026年7月14日 星期二，营业，€100" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2026年7月17日 星期五，未录入，—" })).toBeInTheDocument();
  });

  it("does not show the previous month's dates while another window loads", async () => {
    let releaseJune!: () => void;
    const pendingJune = new Promise<void>((resolve) => { releaseJune = resolve; });
    server.use(
      http.get("/api/database/1/records", async ({ request }) => {
        const start = new URL(request.url).searchParams.get("start");
        if (start === "2026-06-01") {
          await pendingJune;
          return HttpResponse.json(databaseResponse([]));
        }
        return HttpResponse.json(databaseResponse([record]));
      }),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    renderPage();
    await screen.findByRole("button", { name: "2026年7月17日 星期五，未录入，—" });
    fireEvent.click(within(screen.getByLabelText("记录筛选")).getByRole("button", { name: "前一月" }));
    expect(screen.getByText("正在加载记录…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /未录入/ })).not.toBeInTheDocument();
    releaseJune();
    expect(await screen.findByRole("button", { name: "2026年6月30日 星期二，未录入，—" })).toBeInTheDocument();
  });

  it("loads and exports the selected date range without status filtering", async () => {
    const recordRequests: URL[] = [];
    server.use(
      http.get("/api/database/1/records", ({ request }) => {
        recordRequests.push(new URL(request.url));
        return HttpResponse.json(databaseResponse([{ ...record, is_open: "提前休息" }]));
      }),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    renderPage();

    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });
    await waitFor(() => {
      expect(recordRequests.at(-1)?.searchParams.has("status")).toBe(false);
    });
    expect(screen.queryByLabelText("营业状态")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "导出当前范围" }));

    await waitFor(() => {
      expect(downloadBusinessRecords).toHaveBeenCalledWith(
        1,
        { start: "2026-07-01", end: "2026-07-31" },
      );
    });
  });

  it("carries the current records workspace when editing a selected day", async () => {
    Object.defineProperty(window, "scrollY", { configurable: true, value: 240 });
    const juneRecord = { ...record, id: 15, date: "2026-06-15" };
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([juneRecord], 1, 30))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    renderPage();

    fireEvent.click(within(screen.getByRole("region", { name: "记录筛选" })).getByRole("button", { name: "自定义范围" }));
    fireEvent.change(screen.getByLabelText("开始日期"), { target: { value: "2026-06-01" } });
    fireEvent.change(screen.getByLabelText("结束日期"), { target: { value: "2026-06-30" } });
    await screen.findByRole("heading", { name: "2026年6月15日 星期一" });
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    fireEvent.click(screen.getByRole("button", { name: "2026年6月15日 星期一，营业，€100" }));
    const mobileDetail = await screen.findByRole("region", { name: "2026-06-15 营业记录详情" });
    fireEvent.click(within(mobileDetail).getByRole("link", { name: "修改这天记录" }));

    const routeState = screen.getByLabelText("路由状态");
    expect(routeState).toHaveTextContent("/ledger?date=2026-06-15");
    expect(routeState).toHaveTextContent('"returnToBusinessRecords"');
    expect(routeState).toHaveTextContent('"recordMode":"custom"');
    expect(routeState).toHaveTextContent('"range":{"start":"2026-06-01","end":"2026-06-30"}');
    expect(routeState).toHaveTextContent('"page":2');
    expect(routeState).toHaveTextContent('"selectedDate":"2026-06-15"');
    expect(routeState).toHaveTextContent('"mobileRecordDate":"2026-06-15"');
    expect(routeState).not.toHaveTextContent('"analysis"');
    expect(routeState).toHaveTextContent('"scrollY":240');
  });

  it("restores the complete records workspace after a ledger edit", async () => {
    const recordRequests: URL[] = [];
    const chartRequests: URL[] = [];
    const juneRecord = { ...record, id: 15, date: "2026-06-15" };
    window.scrollTo = vi.fn();
    server.use(
      http.get("/api/database/1/records", ({ request }) => {
        recordRequests.push(new URL(request.url));
        return HttpResponse.json(databaseResponse([juneRecord], 1, 30));
      }),
      http.get("/api/charts/1", ({ request }) => {
        chartRequests.push(new URL(request.url));
        return HttpResponse.json(chartsPayload);
      }),
    );

    renderPage("admin", {
      pathname: "/database",
      state: {
        restoreBusinessRecords: {
          storeId: 1,
          recordMode: "custom",
          range: { start: "2026-06-01", end: "2026-06-30" },
          page: 2,
          selectedDate: "2026-06-15",
          mobileRecordDate: "2026-06-15",
          scrollY: 320,
        },
      },
    });

    expect(await screen.findByText("第 2 / 2 页")).toBeInTheDocument();
    expect(recordRequests[0].searchParams.get("start")).toBe("2026-06-01");
    expect(recordRequests[0].searchParams.get("end")).toBe("2026-06-30");
    expect(await screen.findByRole("region", { name: "2026-06-15 营业记录详情" })).toHaveTextContent("2026年6月15日 星期一");
    await waitFor(() => {
      expect(chartRequests.at(-1)?.searchParams.get("start")).toBe("2026-06-01");
      expect(chartRequests.at(-1)?.searchParams.get("end")).toBe("2026-06-30");
    });
    await waitFor(() => expect(screen.getByLabelText("路由状态")).toHaveTextContent("/database?date=2026-06-15|null"));
    fireEvent.click(within(screen.getByRole("region", { name: "2026-06-15 营业记录详情" })).getByRole("button", { name: "返回记录" }));
    await waitFor(() => expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 320 }));
    expect(screen.getByText("第 2 / 2 页")).toBeInTheDocument();
  });

  it("ignores and consumes an invalid restore snapshot", async () => {
    const recordRequests: URL[] = [];
    server.use(
      http.get("/api/database/1/records", ({ request }) => {
        recordRequests.push(new URL(request.url));
        return HttpResponse.json(databaseResponse([record]));
      }),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );

    renderPage("admin", {
      pathname: "/database",
      state: { restoreBusinessRecords: { storeId: 1, recordMode: "custom" } },
    });

    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });
    expect(recordRequests[0].searchParams.get("start")).toBe("2026-07-01");
    expect(recordRequests[0].searchParams.get("end")).toBe("2026-07-31");
    await waitFor(() => expect(screen.getByLabelText("路由状态")).toHaveTextContent("/database|null"));
  });

  it("shows unrecorded dates in the current month table and selects the first saved result", async () => {
    const recordRequests: string[] = [];
    server.use(
      http.get("/api/database/1/records", ({ request }) => {
        recordRequests.push(new URL(request.url).pathname + new URL(request.url).search);
        return HttpResponse.json(databaseResponse([record, { ...record, id: 3, date: "2026-07-13" }]));
      }),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );

    renderPage();

    expect(await screen.findByRole("heading", { name: "2026年7月14日 星期二" })).toBeInTheDocument();
    expect(recordRequests[0]).toBe("/api/database/1/records?start=2026-07-01&end=2026-07-31&page=1&page_size=200");
    expect(screen.getByText("洗车 8 辆")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByRole("row", { name: /2026年7月17日 星期五 未录入 — —/ })).toBeInTheDocument();
  });

  it("shows an editable detail card when an unrecorded date is selected", async () => {
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([record]))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    renderPage();
    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });

    fireEvent.click(within(screen.getByRole("table")).getByText("2026年7月17日 星期五").closest("tr")!);

    const detail = screen.getByRole("complementary");
    expect(await within(detail).findByRole("heading", { name: "2026年7月17日 星期五" })).toBeInTheDocument();
    expect(within(detail).getByText("未录入", { exact: true })).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-17");
    expect(within(detail).queryByRole("button", { name: "删除记录" })).not.toBeInTheDocument();
  });

  it("opens an editable mobile detail for an unrecorded date", async () => {
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([record]))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    renderPage();
    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });

    fireEvent.click(screen.getByRole("button", { name: "2026年7月17日 星期五，未录入，—" }));

    const sheet = await screen.findByRole("region", { name: "2026-07-17 营业记录详情" });
    expect(within(sheet).getByText("未录入", { exact: true })).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-17");
    expect(within(sheet).queryByRole("button", { name: "删除记录" })).not.toBeInTheDocument();
  });

  it("opens the final delete confirmation directly from the mobile detail", async () => {
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([record]))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    renderPage();
    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });

    fireEvent.click(screen.getByRole("button", { name: "2026年7月14日 星期二，营业，€100" }));
    const sheet = await screen.findByRole("region", { name: "2026-07-14 营业记录详情" });
    fireEvent.click(within(sheet).getByRole("button", { name: "删除记录" }));

    expect(await screen.findByRole("alertdialog", { name: "确认永久删除记录？" })).toBeInTheDocument();
    expect(screen.queryByText(/管理 2026-07-14 记录/)).not.toBeInTheDocument();
  });

  it("selects the new page or range's first record and keeps analysis synchronized with record filters", async () => {
    const recordRequests: URL[] = [];
    const chartRequests: URL[] = [];
    server.use(
      http.get("/api/database/1/records", ({ request }) => {
        const url = new URL(request.url);
        recordRequests.push(url);
        if (url.searchParams.get("start") === "2026-06-01") {
          return HttpResponse.json(databaseResponse([{ ...record, id: 20, date: "2026-06-30" }]));
        }
        return HttpResponse.json(databaseResponse([record, { ...record, id: 3, date: "2026-07-13" }], 1, 30));
      }),
      http.get("/api/charts/1", ({ request }) => {
        chartRequests.push(new URL(request.url));
        return HttpResponse.json(chartsPayload);
      }),
    );
    renderPage();
    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });
    await waitFor(() => expect(chartRequests).toHaveLength(1));
    expect(chartRequests[0].searchParams.get("start")).toBe("2026-07-01");
    expect(chartRequests[0].searchParams.get("end")).toBe("2026-07-31");
    expect(screen.queryByLabelText("经营分析日期范围")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(await screen.findByText("第 2 / 2 页")).toBeInTheDocument();
    expect(screen.getAllByText("暂无可查看记录")).toHaveLength(1);
    expect(chartRequests).toHaveLength(1);

    fireEvent.click(within(screen.getByLabelText("记录筛选")).getByRole("button", { name: "前一月" }));
    expect(await screen.findByRole("heading", { name: "2026年6月30日 星期二" })).toBeInTheDocument();
    expect(recordRequests.at(-1)?.searchParams.get("page")).toBe("1");
    await waitFor(() => expect(chartRequests.at(-1)?.searchParams.get("start")).toBe("2026-06-01"));
    expect(chartRequests.at(-1)?.searchParams.get("end")).toBe("2026-06-30");
    expect(chartRequests.at(-1)?.searchParams.get("bucket")).toBe("day");
  });

  it("keeps analysis usable when records fail and keeps records usable when analysis fails", async () => {
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json({ detail: "records failed" }, { status: 500 })),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    const first = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "经营分析" }));
    expect(await screen.findByText("现金")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "记录" }));
    expect(await screen.findByRole("button", { name: "重试" })).toBeInTheDocument();
    first.unmount();

    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([record]))),
      http.get("/api/charts/1", () => HttpResponse.json({ detail: "charts failed" }, { status: 500 })),
    );
    renderPage();
    expect(await screen.findByRole("heading", { name: "2026年7月14日 星期二" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "经营分析" }));
    expect(await screen.findByRole("button", { name: "重试经营分析" })).toBeInTheDocument();
  });

  it("offers backfill alongside usable analysis for an empty record range", async () => {
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([]))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    renderPage();

    await waitFor(() => expect(screen.getAllByText("暂无可查看记录")).toHaveLength(2));
    expect(screen.getAllByRole("link", { name: "补记记录" })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "补记记录" })[0]).toHaveAttribute("href", "/ledger?date=2026-07-17");
    expect(screen.getByRole("button", { name: "经营分析" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("link", { name: "补记记录" })[0]);
    expect(screen.getByLabelText("路由状态")).toHaveTextContent("/ledger?date=2026-07-17");
    expect(screen.getByLabelText("路由状态")).toHaveTextContent('"returnToBusinessRecords"');
  });

  it("resets page, ranges, detail, sheet, and delete state on store change and ignores old responses", async () => {
    let releaseOld!: () => void;
    const delayedOld = new Promise<void>((resolve) => { releaseOld = resolve; });
    const storeTwoRequests: URL[] = [];
    let storeOneRequests = 0;
    server.use(
      http.get("/api/database/1/records", async () => {
        storeOneRequests += 1;
        if (storeOneRequests > 1) await delayedOld;
        return HttpResponse.json(databaseResponse([record], 1, 30));
      }),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
      http.get("/api/database/2/records", ({ request }) => {
        storeTwoRequests.push(new URL(request.url));
        return HttpResponse.json(databaseResponse([{ ...record, id: 4, store_id: 2, date: "2026-07-16" }]));
      }),
      http.get("/api/charts/2", () => HttpResponse.json({ ...chartsPayload, categories: [{ category_id: 2, category_name: "巴黎现金", amount: 100 }] })),
    );
    const view = renderPage();
    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });
    fireEvent.click(screen.getAllByRole("button", { name: "删除记录" }).at(-1)!);
    expect(await screen.findByRole("heading", { name: "确认永久删除记录？" })).toBeInTheDocument();
    void view.client.invalidateQueries({ queryKey: ["database", "records", 1] });
    await waitFor(() => expect(storeOneRequests).toBe(2));

    selectedStore = paris;
    view.rerender(
      <MemoryRouter>
        <QueryClientProvider client={view.client}><BusinessRecordsPage /></QueryClientProvider>
      </MemoryRouter>,
    );

    expect(screen.queryByRole("heading", { name: "2026年7月14日 星期二" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "2026年7月16日 星期四" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "2026年7月14日 星期二，营业，€100" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2026年7月14日 星期二，未录入，—" })).toBeInTheDocument();
    expect(storeTwoRequests[0].pathname + storeTwoRequests[0].search).toBe("/api/database/2/records?start=2026-07-01&end=2026-07-31&page=1&page_size=200");
    expect(screen.queryByRole("region", { name: "2026-07-14 营业记录详情" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "确认永久删除记录？" })).not.toBeInTheDocument();
    releaseOld();
  });

  it("exports only the current record range and isolates export failures", async () => {
    server.use(
      http.get("/api/database/1/records", () => {
        return HttpResponse.json(databaseResponse([record], 1, 30));
      }),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    vi.mocked(downloadBusinessRecords).mockRejectedValueOnce(new Error("offline"));
    renderPage();
    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    fireEvent.click(screen.getByRole("button", { name: "导出当前范围" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("导出失败，请重试");
    expect(downloadBusinessRecords).toHaveBeenCalledWith(1, { start: "2026-07-01", end: "2026-07-31" });
    expect(screen.getByText("第 2 / 2 页")).toBeInTheDocument();
    expect(screen.getAllByText("暂无可查看记录")).toHaveLength(1);
  });

  it("lets ordinary users edit any selected record without exposing delete actions", async () => {
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([record, { ...record, id: 6, date: "2026-07-15" }]))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
    );
    renderPage("user");
    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });

    expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-14");
    expect(screen.queryByRole("button", { name: "删除记录" })).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("table")).getByText("2026年7月15日 星期三").closest("tr")!);
    expect(await screen.findByRole("heading", { name: "2026年7月15日 星期三" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-15");
  });

  it("lets administrators permanently delete without history, rollback, or version requests", async () => {
    let deleted = false;
    let deleteUrl = "";
    let chartRequests = 0;
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse(deleted ? [] : [record]))),
      http.get("/api/charts/1", () => {
        chartRequests += 1;
        return HttpResponse.json(chartsPayload);
      }),
      http.delete("/api/ledger/1/2026-07-14", ({ request }) => {
        deleteUrl = request.url;
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderPage();
    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });
    await waitFor(() => expect(chartRequests).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "删除记录" }));
    expect(await screen.findByRole("heading", { name: "确认永久删除记录？" })).toBeInTheDocument();
    expect(screen.queryByText(/管理 2026-07-14 记录/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认永久删除" }));
    await waitFor(() => expect(deleted).toBe(true));
    expect(new URL(deleteUrl).search).toBe("");
    expect(await screen.findByRole("status")).toHaveTextContent("删除成功");
    expect((await screen.findAllByText("暂无可查看记录")).length).toBeGreaterThan(0);
    await waitFor(() => expect(chartRequests).toBe(2));
    const remainingDetail = screen.getByRole("complementary");
    expect(remainingDetail).toHaveTextContent("未录入");
    expect(within(remainingDetail).queryByRole("button", { name: "删除记录" })).not.toBeInTheDocument();
    expect(screen.queryByText(/历史|回滚/)).not.toBeInTheDocument();
  });

  it("keeps permanent deletion retryable after an API failure", async () => {
    let deleteRequests = 0;
    server.use(
      http.get("/api/database/1/records", () => HttpResponse.json(databaseResponse([record]))),
      http.get("/api/charts/1", () => HttpResponse.json(chartsPayload)),
      http.delete("/api/ledger/1/2026-07-14", () => {
        deleteRequests += 1;
        return HttpResponse.json({ detail: "Record changed" }, { status: 409 });
      }),
    );
    renderPage();
    await screen.findByRole("heading", { name: "2026年7月14日 星期二" });
    fireEvent.click(screen.getByRole("button", { name: "删除记录" }));
    expect(await screen.findByRole("heading", { name: "确认永久删除记录？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认永久删除" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("数据已经发生变化，请刷新后重试");
    fireEvent.click(screen.getByRole("button", { name: "确认永久删除" }));
    await waitFor(() => expect(deleteRequests).toBe(2));
  });
});
