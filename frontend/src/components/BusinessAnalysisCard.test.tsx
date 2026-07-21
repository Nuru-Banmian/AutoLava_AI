import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import type { ChartsResponse } from "@/api/types";
import { BusinessAnalysisCard } from "@/components/BusinessAnalysisCard";

const server = setupServer();

function payload(overrides: Partial<ChartsResponse> = {}): ChartsResponse {
  return {
    kpis: { total_revenue: 100, record_days: 2, open_days: 2, average_revenue: 50, primary_categories: [], total_wash_count: null, average_ticket: null },
    range: { start: "2026-07-01", end: "2026-07-17", bucket: "day" },
    comparison_kpis: { start: "2026-06-01", end: "2026-06-17", total_revenue: 80, open_days: 2, average_revenue: 40 },
    income_summary: { daily_ledger_revenue: 100, confirmed_settlement_income: 0, total_income: 100, includes_settlement_income: false },
    classified_included_total: 100,
    daily: [{ date: "2026-07-01", revenue: 100 }],
    categories: [{ category_id: 1, category_name: "现金收入", amount: 100 }],
    excluded_categories: [{ category_id: 2, category_name: "代收款", amount: 20 }],
    monthly: [{ month: "2026-07", revenue: 100, daily_ledger_revenue: 100, confirmed_settlement_income: null, monthly_total_income: null }],
    weather: [],
    weekday: [],
    ...overrides,
  };
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><BusinessAnalysisCard storeId={1} today="2026-07-17" /></QueryClientProvider>);
  return client;
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("BusinessAnalysisCard", () => {
  it("drives KPI, trend, and both composition groups from one range query", async () => {
    const requests: URL[] = [];
    server.use(http.get("/api/charts/1", ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      const isSixMonths = url.searchParams.get("bucket") === "month";
      const isCustom = url.searchParams.get("start") === "2026-07-02";
      const response: Partial<ChartsResponse> = isSixMonths ? {
        kpis: { ...payload().kpis, total_revenue: 600 },
        range: { start: "2026-02-01", end: "2026-07-17", bucket: "month" },
        categories: [{ category_id: 3, category_name: "月度收入", amount: 600 }],
        excluded_categories: [{ category_id: 4, category_name: "月度排除", amount: 30 }],
      } : isCustom ? {
        kpis: { ...payload().kpis, total_revenue: 200 },
        range: { start: "2026-07-02", end: "2026-07-03", bucket: "day" },
        comparison_kpis: null,
        categories: [{ category_id: 5, category_name: "自定义收入", amount: 200 }],
        excluded_categories: [{ category_id: 6, category_name: "自定义排除", amount: 5 }],
      } : payload();
      return HttpResponse.json(payload(response));
    }));

    const user = userEvent.setup();
    renderCard();

    await screen.findByText("现金收入");
    expect(screen.getByTestId("chart-panel-plot")).toHaveClass("h-64", "min-h-64");
    expect(requests[0].pathname + requests[0].search).toBe("/api/charts/1?start=2026-07-01&end=2026-07-17&bucket=day&compare_start=2026-06-01&compare_end=2026-06-17");
    expect(screen.getByText("比较区间：2026-06-01 至 2026-06-17")).toBeInTheDocument();
    expect(screen.getByText(/按日/)).toBeInTheDocument();
    expect(screen.getByText("代收款")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "近 6 月" }));
    await screen.findByText("月度收入");
    expect(requests.at(-1)?.searchParams.get("bucket")).toBe("month");
    expect(screen.getAllByText("€600").length).toBeGreaterThan(0);
    expect(screen.getByText("月度排除")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "自定义" }));
    expect(screen.getByLabelText("分析开始日期")).toHaveClass("h-10", "min-w-0", "pr-10");
    expect(screen.getByLabelText("分析结束日期")).toHaveClass("h-10", "min-w-0", "pr-10");
    fireEvent.change(screen.getByLabelText("分析开始日期"), { target: { value: "2026-07-02" } });
    fireEvent.change(screen.getByLabelText("分析结束日期"), { target: { value: "2026-07-03" } });
    await screen.findByText("自定义收入");
    const customRequest = requests.at(-1)!;
    expect(customRequest.searchParams.get("compare_start")).toBeNull();
    expect(customRequest.searchParams.get("compare_end")).toBeNull();
    expect(screen.getAllByText("€200").length).toBeGreaterThan(0);
    expect(screen.getByText("自定义排除")).toBeInTheDocument();
  });

  it("renders the zero-data and retry states", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json(payload({
      kpis: { ...payload().kpis, total_revenue: 0, open_days: 0 },
      income_summary: { daily_ledger_revenue: 0, confirmed_settlement_income: 0, total_income: 0, includes_settlement_income: false },
      daily: [],
      categories: [],
      excluded_categories: [],
    }))));

    renderCard();
    expect(await screen.findByText("该范围暂无经营数据")).toBeInTheDocument();

    server.use(http.get("/api/charts/1", () => HttpResponse.json({ detail: "failed" }, { status: 500 })));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "近 6 月" }));
    expect(await screen.findByRole("button", { name: "重试经营分析" })).toBeInTheDocument();
  });

  it("keeps cached content visible and labels a failed refresh", async () => {
    let fail = false;
    server.use(http.get("/api/charts/1", () => fail ? HttpResponse.json({ detail: "failed" }, { status: 500 }) : HttpResponse.json(payload())));
    const client = renderCard();

    expect((await screen.findAllByText("€100")).length).toBeGreaterThan(0);
    fail = true;
    await client.invalidateQueries({ queryKey: ["charts", 1] });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("刷新失败"));
    expect(screen.getAllByText("€100").length).toBeGreaterThan(0);
  });

  it("avoids a numeric comparison when the prior total is zero", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json(payload({ comparison_kpis: { start: "2026-06-01", end: "2026-06-17", total_revenue: 0, open_days: 0, average_revenue: 0 } }))));
    renderCard();

    expect(await screen.findByText("上期为 0，暂无可比增幅")).toBeInTheDocument();
    expect(screen.queryByText(/Infinity|NaN/)).not.toBeInTheDocument();
  });

  it("clearly splits income for a complete-month analysis", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json(payload({
      kpis: { ...payload().kpis, total_revenue: 420 },
      range: { start: "2026-06-01", end: "2026-06-30", bucket: "month" },
      income_summary: {
        daily_ledger_revenue: 300,
        confirmed_settlement_income: 120,
        total_income: 420,
        includes_settlement_income: true,
      },
    }))));
    renderCard();

    expect(await screen.findByText("日常营业额")).toBeInTheDocument();
    expect(screen.getByText("公司结算收入")).toBeInTheDocument();
    expect(screen.getByText("月度总收入")).toBeInTheDocument();
    expect(screen.getByText("€300")).toBeInTheDocument();
    expect(screen.getByText("€120")).toBeInTheDocument();
    expect(screen.getByText("€420")).toBeInTheDocument();
  });
});
