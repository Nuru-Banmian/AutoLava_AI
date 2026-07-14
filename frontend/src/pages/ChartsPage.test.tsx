import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ChartsPage } from "@/pages/ChartsPage";
import { StoreProvider } from "@/stores/StoreProvider";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("ChartsPage", () => {
  it("hides wash metrics when the API returns null and shows primary details", async () => {
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
      http.get("/api/database/1/records", () => HttpResponse.json({ items: [], categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 })),
      http.get("/api/charts/1", () => HttpResponse.json({ kpis: { total_revenue: "350.00", record_days: 2, open_days: 1, primary_categories: [{ category_id: 1, category_name: "现金", amount: "300.00" }], total_wash_count: null, average_ticket: null }, daily: [], categories: [], monthly: [], weather: [], weekday: [] })),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><StoreProvider><ChartsPage /></StoreProvider></QueryClientProvider>);
    expect(await screen.findByText("总收入")).toBeInTheDocument();
    expect(screen.getByText("现金 €300.00")).toBeInTheDocument();
    expect(screen.queryByText("平均客单价")).not.toBeInTheDocument();
  });

  it("sends repeated selected category parameters and renders empty panels safely", async () => {
    let url = new URL("http://x");
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
      http.get("/api/database/1/records", () => HttpResponse.json({ items: [], categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }, { id: 2, name: "刷卡", include_in_total: false, is_active: true, sort_order: 2 }], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 })),
      http.get("/api/charts/1", ({ request }) => { url = new URL(request.url); return HttpResponse.json({ kpis: { total_revenue: "0", record_days: 0, open_days: 0, primary_categories: [], total_wash_count: null, average_ticket: null }, daily: [], categories: [], monthly: [], weather: [], weekday: [] }); }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); render(<QueryClientProvider client={client}><StoreProvider><ChartsPage /></StoreProvider></QueryClientProvider>);
    expect(await screen.findByText("总收入")).toBeInTheDocument(); expect(url.searchParams.getAll("category_id")).toEqual(["1"]);
    fireEvent.click(screen.getByLabelText("刷卡")); await waitFor(() => expect(url.searchParams.getAll("category_id")).toEqual(["1", "2"]));
    expect(screen.getAllByText("暂无数据").length).toBeGreaterThanOrEqual(5); expect(screen.queryByRole("button", { name: /全选/ })).not.toBeInTheDocument();
  });

  it("does not query backend defaults when no category is selected", async () => {
    let calls = 0;
    server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])), http.get("/api/database/1/records", () => HttpResponse.json({ items: [], categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 })), http.get("/api/charts/1", () => { calls += 1; return HttpResponse.json({ kpis: { total_revenue: "0", record_days: 0, open_days: 0, primary_categories: [], total_wash_count: null, average_ticket: null }, daily: [], categories: [], monthly: [], weather: [], weekday: [] }); }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); render(<QueryClientProvider client={client}><StoreProvider><ChartsPage /></StoreProvider></QueryClientProvider>);
    await screen.findByText("总收入"); expect(calls).toBe(1); fireEvent.click(screen.getByLabelText("现金"));
    expect(await screen.findByText("请至少选择一个收入分类。")).toBeInTheDocument(); await new Promise((resolve) => setTimeout(resolve, 20)); expect(calls).toBe(1);
  });

  it("scopes the catalog to the selected range and shows inactive historical categories", async () => {
    const catalogRequests: URL[] = [];
    server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])), http.get("/api/database/1/records", ({ request }) => { const url = new URL(request.url); catalogRequests.push(url); const historical = url.searchParams.get("start") === "2026-06-01"; return HttpResponse.json({ items: [], categories: historical ? [{ id: 8, name: "历史现金", include_in_total: true, is_active: false, sort_order: 1 }] : [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 }); }), http.get("/api/charts/1", () => HttpResponse.json({ kpis: { total_revenue: "0", record_days: 0, open_days: 0, primary_categories: [], total_wash_count: null, average_ticket: null }, daily: [], categories: [], monthly: [], weather: [], weekday: [] })));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); render(<QueryClientProvider client={client}><StoreProvider><ChartsPage /></StoreProvider></QueryClientProvider>);
    await screen.findByLabelText("现金"); fireEvent.change(screen.getByLabelText("图表开始日期"), { target: { value: "2026-06-01" } }); fireEvent.change(screen.getByLabelText("图表结束日期"), { target: { value: "2026-06-30" } });
    expect(await screen.findByLabelText("历史现金（已停用）")).toBeChecked(); expect(catalogRequests.at(-1)?.searchParams.get("end")).toBe("2026-06-30");
  });

  it("shows catalog errors with retry instead of an empty selector", async () => {
    let calls = 0; server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])), http.get("/api/database/1/records", () => { calls += 1; return calls === 1 ? HttpResponse.json({ detail: "Catalog unavailable" }, { status: 500 }) : HttpResponse.json({ items: [], categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 }); }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); render(<QueryClientProvider client={client}><StoreProvider><ChartsPage /></StoreProvider></QueryClientProvider>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Catalog unavailable"); expect(screen.queryByText("请至少选择一个收入分类。")).not.toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "重试分类" })); expect(await screen.findByLabelText("现金")).toBeChecked();
  });

  it("does not issue a range query with stale category selections", async () => {
    const chartUrls: URL[] = [];
    server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])), http.get("/api/database/1/records", ({ request }) => { const historical = new URL(request.url).searchParams.get("start") === "2026-06-01"; return HttpResponse.json({ items: [], categories: [{ id: historical ? 8 : 1, name: historical ? "历史" : "当前", include_in_total: true, is_active: true, sort_order: 1 }], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 }); }), http.get("/api/charts/1", ({ request }) => { chartUrls.push(new URL(request.url)); return HttpResponse.json({ kpis: { total_revenue: "0", record_days: 0, open_days: 0, primary_categories: [], total_wash_count: null, average_ticket: null }, daily: [], categories: [], monthly: [], weather: [], weekday: [] }); }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); render(<QueryClientProvider client={client}><StoreProvider><ChartsPage /></StoreProvider></QueryClientProvider>); await screen.findByLabelText("当前");
    fireEvent.change(screen.getByLabelText("图表开始日期"), { target: { value: "2026-06-01" } }); fireEvent.change(screen.getByLabelText("图表结束日期"), { target: { value: "2026-06-30" } }); await screen.findByLabelText("历史");
    await waitFor(() => expect(chartUrls.some((url) => url.searchParams.get("start") === "2026-06-01" && url.searchParams.getAll("category_id").join() === "8")).toBe(true)); expect(chartUrls.some((url) => url.searchParams.get("start") === "2026-06-01" && url.searchParams.has("category_id", "1"))).toBe(false);
  });

  it("keeps large KPI and primary decimal strings exact", async () => {
    server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])), http.get("/api/database/1/records", () => HttpResponse.json({ items: [], categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 })), http.get("/api/charts/1", () => HttpResponse.json({ kpis: { total_revenue: "9007199254740993.10", record_days: 1, open_days: 1, primary_categories: [{ category_id: 1, category_name: "现金", amount: "9007199254740993.10" }], total_wash_count: null, average_ticket: null }, daily: [], categories: [], monthly: [], weather: [], weekday: [] })));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); render(<QueryClientProvider client={client}><StoreProvider><ChartsPage /></StoreProvider></QueryClientProvider>);
    expect((await screen.findAllByText(/€9007199254740993\.10/)).length).toBeGreaterThanOrEqual(2);
  });
});
