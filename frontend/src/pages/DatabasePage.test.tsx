import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { DatabasePage } from "@/pages/DatabasePage";
import { StoreProvider } from "@/stores/StoreProvider";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("DatabasePage", () => {
  it("renders category columns returned by the filtered records response", async () => {
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
      http.get("/api/database/1/records", () => HttpResponse.json({ items: [], categories: [
        { id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 },
        { id: 8, name: "历史分类", include_in_total: false, is_active: false, sort_order: 8 },
      ], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 50 })),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><StoreProvider><DatabasePage /></StoreProvider></QueryClientProvider>);
    expect(await screen.findByRole("columnheader", { name: "现金" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "历史分类" })).toBeInTheDocument();
  });

  const record = { id: 4, store_id: 1, date: "2026-07-13", daily_revenue: "10.00", wash_count: 2, is_open: "营业", weather: "晴", weather_auto: "晴", weather_code: 1, temperature_max: "20.0", temperature_min: "10.0", precipitation: "0.0", activity: "夏日 活动", weather_edited: false, scanned: false, created_by: 1, updated_by: 1, created_at: "2026-07-13T00:00:00", updated_at: "2026-07-13T00:00:00", created_by_name: "u", updated_by_name: "u", items: [{ id: 1, category_id: 1, amount: "10.00", created_at: "", updated_at: "" }] } as any;
  function renderPage(extra: Parameters<typeof server.use>) {
    server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])), ...extra, http.get("/api/database/1/history", () => HttpResponse.json([])));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><StoreProvider><DatabasePage /></StoreProvider></QueryClientProvider>);
  }

  it("uses the exact same encoded filters for records and export", async () => {
    let last = new URL("http://x");
    renderPage([http.get("/api/database/1/records", ({ request }) => { last = new URL(request.url); return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0", total: 0, page: 1, page_size: 50 }); })]);
    await screen.findByText("0 条 · 合计 €0.00");
    fireEvent.change(screen.getByLabelText("筛选状态"), { target: { value: "营业" } }); fireEvent.change(screen.getByLabelText("筛选天气"), { target: { value: "晴 & 雨" } }); fireEvent.change(screen.getByLabelText("活动搜索"), { target: { value: "夏日 活动" } }); fireEvent.click(screen.getByLabelText("缺少洗车数量"));
    await waitFor(() => expect(last.searchParams.get("activity_query")).toBe("夏日 活动"));
    const recordsParams = new URLSearchParams(last.search); recordsParams.delete("page"); recordsParams.delete("page_size");
    const exportParams = new URL((screen.getByRole("button", { name: "导出 Excel" }) as HTMLAnchorElement).href).searchParams;
    expect(exportParams.toString()).toBe(recordsParams.toString());
  });

  it("builds inclusive store-local quick ranges", async () => {
    let last = new URL("http://x");
    renderPage([http.get("/api/database/1/records", ({ request }) => { last = new URL(request.url); return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0", total: 0, page: 1, page_size: 50 }); })]);
    await screen.findByText("0 条 · 合计 €0.00"); fireEvent.click(screen.getByRole("button", { name: "本月" }));
    await waitFor(() => expect(last.searchParams.get("start")).toBe("2026-07-01")); expect(last.searchParams.get("end")).toBe("2026-07-14");
    fireEvent.click(screen.getByRole("button", { name: "上月" })); await waitFor(() => expect(last.searchParams.get("start")).toBe("2026-06-01")); expect(last.searchParams.get("end")).toBe("2026-06-30");
    fireEvent.click(screen.getByRole("button", { name: "最近7天" })); await waitFor(() => expect(last.searchParams.get("start")).toBe("2026-07-08")); expect(last.searchParams.get("end")).toBe("2026-07-14");
    fireEvent.click(screen.getByRole("button", { name: "最近30天" })); await waitFor(() => expect(last.searchParams.get("start")).toBe("2026-06-15")); expect(last.searchParams.get("end")).toBe("2026-07-14");
  });

  it("requires confirmation for delete and rollback and edits with overwrite", async () => {
    let deleted = 0; let rolled = 0; let edited = "";
    renderPage([
      http.get("/api/database/1/records", () => HttpResponse.json({ items: [record], categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], sum_daily_revenue: "10", total: 1, page: 1, page_size: 50 })),
      http.get("/api/database/1/history", () => HttpResponse.json([{ id: 9, record_id: 4, record_date: "2026-07-13", operation_type: "update", operation_source: "manual", operator_user_id: 1, operator_username: "u", before: record, after: record, description: "x", requires_approval: false, approved: true, created_at: "" }])),
      http.put("/api/ledger/1/2026-07-13", ({ request }) => { edited = new URL(request.url).searchParams.get("overwrite") ?? ""; return HttpResponse.json({}); }),
      http.delete("/api/ledger/1/2026-07-13", () => { deleted += 1; return new HttpResponse(null, { status: 204 }); }),
      http.post("/api/database/1/history/9/rollback", () => { rolled += 1; return HttpResponse.json({ audit_id: 9, record }); }),
    ]);
    fireEvent.click(await screen.findByRole("button", { name: "编辑 2026-07-13" })); fireEvent.click(screen.getByRole("button", { name: "保存" })); await waitFor(() => expect(edited).toBe("true"));
    fireEvent.click(await screen.findByRole("button", { name: "删除 2026-07-13" })); expect(deleted).toBe(0); fireEvent.click(screen.getByRole("button", { name: "确认删除" })); await waitFor(() => expect(deleted).toBe(1));
    fireEvent.click(await screen.findByRole("button", { name: "回滚 #9" })); expect(rolled).toBe(0); fireEvent.click(screen.getByRole("button", { name: "确认回滚" })); await waitFor(() => expect(rolled).toBe(1));
  });
});
