import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { RecordSnapshot, UserRole } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { DatabasePage } from "@/pages/DatabasePage";
import { StoreProvider } from "@/stores/StoreProvider";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: vi.fn() }));

const server = setupServer();
const record: RecordSnapshot = {
  id: 4,
  store_id: 1,
  date: "2026-07-14",
  daily_revenue: "100.00",
  income_mode: "composed",
  income_config_version_id: 3,
  row_version: 1,
  wash_count: 8,
  is_open: "营业",
  weather: "晴",
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
  items: [{ id: 1, category_id: 1, category_name: "现金", include_in_total: true, sort_order: 1, amount: "100.00", created_at: "", updated_at: "" }],
};

function renderPage({ records = [record], recordsProvider, recordsDelay, recordsError = false, role = "admin", history = [], onHistoryRequest }: { records?: RecordSnapshot[]; recordsProvider?: () => RecordSnapshot[]; recordsDelay?: Promise<void>; recordsError?: boolean; role?: UserRole; history?: object[]; onHistoryRequest?: (url: URL) => void } = {}) {
  vi.mocked(useAuth).mockReturnValue({
    user: { id: role === "admin" ? 1 : 2, username: role, role, is_owner: role === "admin" },
    isLoading: false,
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    isLoggingIn: false,
    isLoggingOut: false,
    logoutError: null,
  });
  server.use(
    http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
    http.get("/api/database/1/records", async ({ request }) => {
      const url = new URL(request.url);
      expect(url.searchParams.get("start")).toBe("2026-07-01");
      expect(url.searchParams.get("end")).toBe("2026-07-31");
      expect(url.searchParams.get("page_size")).toBe("31");
      if (recordsDelay) await recordsDelay;
      if (recordsError) return HttpResponse.json({ detail: "records failed" }, { status: 500 });
      const currentRecords = recordsProvider?.() ?? records;
      return HttpResponse.json({ items: currentRecords, categories: [], sum_daily_revenue: currentRecords.reduce((sum, item) => sum + Number(item.daily_revenue), 0).toFixed(2), total: currentRecords.length, page: 1, page_size: 31 });
    }),
    http.get("/api/database/1/history", ({ request }) => {
      onHistoryRequest?.(new URL(request.url));
      return HttpResponse.json({ items: history, total: history.length, page: 1, page_size: 20 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <MemoryRouter>
      <QueryClientProvider client={client}><StoreProvider><DatabasePage /></StoreProvider></QueryClientProvider>
    </MemoryRouter>,
  );
  return client;
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-07-15T10:00:00Z"));
});
afterEach(() => { vi.useRealTimers(); server.resetHandlers(); });
afterAll(() => server.close());

describe("DatabasePage", () => {
  it("uses a marked calendar as the only record discovery control", async () => {
    renderPage();

    expect(await screen.findByRole("button", { name: "2026年7月14日，已有记录" })).toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "补记一天" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("record-table-scroll")).not.toBeInTheDocument();
  });

  it("shows compact month summaries and selected record detail", async () => {
    renderPage({ records: [record, { ...record, id: 5, date: "2026-07-13", daily_revenue: "50.00", is_open: "休息" }] });

    expect(await screen.findByText("€150.00")).toBeInTheDocument();
    expect(screen.getByText("已记录 2 天")).toBeInTheDocument();
    expect(screen.getByText("营业日均 €100.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2026年7月14日，已有记录" }));
    expect(await screen.findByRole("heading", { name: "2026年7月14日" })).toBeInTheDocument();
    expect(screen.getByText("洗车数量 8")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-14");
  });

  it("shows a selected missing day with one contextual backfill action", async () => {
    renderPage();

    const todayButton = await screen.findByRole("button", { name: "2026年7月15日" });
    fireEvent.click(todayButton);
    expect(screen.getByText("2026年7月15日尚未记录")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "补记这一天" })).toHaveAttribute("href", "/ledger?date=2026-07-15");
  });

  it("does not advertise a missing record while the month request is pending", async () => {
    const pending = new Promise<void>(() => undefined);
    renderPage({ recordsDelay: pending });

    expect(await screen.findByText("本月营业额")).toBeInTheDocument();
    expect(screen.getByText("加载记录…")).toBeInTheDocument();
    expect(screen.queryByText(/尚未记录/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "补记这一天" })).not.toBeInTheDocument();
  });

  it("does not advertise a missing record when the month request fails", async () => {
    renderPage({ recordsError: true });

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/尚未记录/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "补记这一天" })).not.toBeInTheDocument();
  });

  it("does not fabricate category composition for a historical total-only record", async () => {
    renderPage({ records: [{ ...record, income_mode: "legacy_total", items: [] }] });

    fireEvent.click(await screen.findByRole("button", { name: "2026年7月14日，已有记录" }));
    expect(screen.getByText("历史记录仅保存营业额总计")).toBeInTheDocument();
    expect(screen.queryByText("现金")).not.toBeInTheDocument();
    expect(screen.getAllByText("€100.00").length).toBeGreaterThanOrEqual(2);
  });

  it("keeps delete and rollback behind a secondary admin action", async () => {
    let deleted = false;
    let rolled = 0;
    let deleteUrl = "";
    const historyRequests: URL[] = [];
    const audit = { id: 9, record_id: 4, record_date: "2026-07-14", operation_type: "update", operation_source: "manual", operator_user_id: 1, operator_username: "admin", before: record, after: record, description: "修改", requires_approval: false, approved: true, rollbackable: true, created_at: "" };
    renderPage({ recordsProvider: () => deleted ? [] : [record], history: [audit], onHistoryRequest: (url) => historyRequests.push(url) });
    server.use(
      http.delete("/api/ledger/1/2026-07-14", ({ request }) => { deleteUrl = request.url; deleted = true; return new HttpResponse(null, { status: 204 }); }),
      http.post("/api/database/1/history/9/rollback", () => { rolled += 1; deleted = false; return HttpResponse.json({ audit_id: 9, record }); }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "2026年7月14日，已有记录" }));
    expect(screen.queryByRole("button", { name: "删除这天记录" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "管理这天记录" }));
    await waitFor(() => expect(historyRequests.some((url) => url.searchParams.get("record_id") === "4" && !url.searchParams.has("record_date"))).toBe(true));
    fireEvent.click(await screen.findByRole("button", { name: "删除这天记录" }));
    expect(deleted).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(deleted).toBe(true));
    expect(new URL(deleteUrl).search).toBe("?expected_version=1");
    expect(await screen.findByRole("button", { name: "回滚 #9" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(await screen.findByText("2026年7月14日尚未记录")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "管理这天审计" }));
    await waitFor(() => expect(historyRequests.some((url) => url.searchParams.get("record_date") === "2026-07-14" && url.searchParams.get("page_size") === "100" && !url.searchParams.has("record_id"))).toBe(true));
    fireEvent.click(await screen.findByRole("button", { name: "回滚 #9" }));
    expect(rolled).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "确认回滚" }));
    await waitFor(() => expect(rolled).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(await screen.findByRole("heading", { name: "2026年7月14日" })).toBeInTheDocument();
  });

  it("keeps the selected record and explains a stale delete conflict", async () => {
    let deleteUrl = "";
    let recordRequests = 0;
    renderPage({ recordsProvider: () => {
      recordRequests += 1;
      return [{ ...record, row_version: recordRequests > 1 ? 2 : 1 }];
    } });
    server.use(
      http.delete("/api/ledger/1/2026-07-14", ({ request }) => {
        deleteUrl = request.url;
        return HttpResponse.json({ detail: "Record changed; reload before saving" }, { status: 409 });
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "2026年7月14日，已有记录" }));
    fireEvent.click(screen.getByRole("button", { name: "管理这天记录" }));
    fireEvent.click(await screen.findByRole("button", { name: "删除这天记录" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("数据已经发生变化，请刷新后重试");
    expect(new URL(deleteUrl).search).toBe("?expected_version=1");
    expect(screen.getByRole("heading", { name: "确认删除记录？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新加载记录" }));
    await waitFor(() => expect(recordRequests).toBeGreaterThan(1));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(new URL(deleteUrl).search).toBe("?expected_version=2"));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByRole("heading", { name: "2026年7月14日" })).toBeInTheDocument();
  });

  it("lets ordinary users edit any existing date and never exposes admin actions", async () => {
    renderPage({ records: [record, { ...record, id: 6, date: "2026-07-15" }], role: "user" });

    fireEvent.click(await screen.findByRole("button", { name: "2026年7月14日，已有记录" }));
    expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-14");
    expect(screen.queryByRole("button", { name: "管理这天记录" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2026年7月15日，已有记录" }));
    expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-15");
  });
});
