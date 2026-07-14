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
});
