import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import type { ChartsResponse } from "@/api/types";
import { BusinessAnalysisCard } from "@/components/BusinessAnalysisCard";
import type { DateRange } from "@/lib/business-record-ranges";

const server = setupServer();

function payload(overrides: Partial<ChartsResponse> = {}): ChartsResponse {
  return {
    kpis: { total_revenue: 100, record_days: 2, open_days: 2, average_revenue: 50, primary_categories: [], total_wash_count: null, wash_count_covered_days: 0, wash_count_coverage_status: "missing", average_ticket: null },
    range: { start: "2026-07-01", end: "2026-07-17", bucket: "day" },
    comparison_kpis: { start: "2026-06-01", end: "2026-06-17", total_revenue: 80, open_days: 2, average_revenue: 40 },
    income_summary: { daily_ledger_revenue: 100, confirmed_settlement_income: 0, total_income: 100, includes_settlement_income: false },
    classified_included_total: 100,
    daily: [{ date: "2026-07-01", revenue: 100 }],
    categories: [{ category_id: 1, category_name: "现金收入", amount: 100 }],
    excluded_categories: [{ category_id: 2, category_name: "代收款", amount: 20 }],
    monthly: [{ month: "2026-07", revenue: 100, daily_ledger_revenue: 100, confirmed_settlement_income: 0, monthly_total_income: 100 }],
    weather: [],
    weekday: [],
    ...overrides,
  };
}

function renderCard(range: DateRange = { start: "2026-07-01", end: "2026-07-17" }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><BusinessAnalysisCard storeId={1} range={range} /></QueryClientProvider>);
  return { ...view, client };
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("BusinessAnalysisCard", () => {
  it("shows daily ledger coverage and readable missing, closed and zero values independently of settlements", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json({
      ...payload(),
      range: { start: "2026-07-01", end: "2026-07-04", bucket: "day" },
      income_summary: { daily_ledger_revenue: 100, confirmed_settlement_income: 900, total_income: 1000, includes_settlement_income: true },
      daily: [{ date: "2026-07-01", revenue: 100, is_open: "提前休息" }, { date: "2026-07-03", revenue: 0, is_open: "休息" }, { date: "2026-07-04", revenue: 0, is_open: "营业" }],
      comparison_daily: [{ date: "2026-06-01", revenue: 80, is_open: "营业" }],
      period_coverage: { start: "2026-07-01", end: "2026-07-04", record_days: 3, interval_days: 4 },
      comparison_coverage: { start: "2026-06-01", end: "2026-06-04", record_days: 1, interval_days: 4 },
      ledger_comparison: { current_revenue: 100, previous_revenue: 80, change_percent: 25, status: "comparable", short_previous_month: false },
    })));
    renderCard({ start: "2026-07-01", end: "2026-07-04" });
    expect(await screen.findByText("本期已记录 3 / 4 天；上期已记录 1 / 4 天")).toBeInTheDocument();
    expect(screen.getByText("记录覆盖不完整，比较仅反映已记录每日台账。")).toBeInTheDocument();
    expect(screen.getByText("每日台账营业额较上期 +25.0%")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("趋势读数日期"), { target: { value: "2026-07-02" } });
    expect(screen.getByRole("status", { name: "趋势读数" })).toHaveTextContent("2026-07-02：未录入，—");
    fireEvent.change(screen.getByLabelText("趋势读数日期"), { target: { value: "2026-07-03" } });
    expect(screen.getByRole("status", { name: "趋势读数" })).toHaveTextContent("2026-07-03：休息，€0");
    fireEvent.change(screen.getByLabelText("趋势读数日期"), { target: { value: "2026-07-04" } });
    expect(screen.getByRole("status", { name: "趋势读数" })).toHaveTextContent("2026-07-04：营业，€0");
  });
  it("drives all analysis content from the supplied record-table range without separate controls", async () => {
    const requests: URL[] = [];
    server.use(http.get("/api/charts/1", ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      return HttpResponse.json(payload());
    }));

    renderCard();

    await screen.findByText("现金收入");
    expect(screen.getByTestId("chart-panel-plot")).toHaveClass("h-64", "min-h-64");
    expect(requests[0].pathname + requests[0].search).toBe("/api/charts/1?start=2026-07-01&end=2026-07-17&bucket=day");
    expect(screen.queryByLabelText("经营分析日期范围")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("分析开始日期")).not.toBeInTheDocument();
    expect(screen.getByText("比较区间：2026-06-01 至 2026-06-17")).toBeInTheDocument();
    expect(screen.getByText(/按日/)).toBeInTheDocument();
    expect(screen.getByText("经营日")).toBeInTheDocument();
    expect(screen.getByText("经营日均台账营业额")).toBeInTheDocument();
    expect(screen.getByText("代收款")).toBeInTheDocument();
  });

  it("renders the zero-data and retry states", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json(payload({
      kpis: { ...payload().kpis, total_revenue: 0, record_days: 0, open_days: 0 },
      income_summary: { daily_ledger_revenue: 0, confirmed_settlement_income: 0, total_income: 0, includes_settlement_income: false },
      daily: [],
      categories: [],
      excluded_categories: [],
    }))));

    const first = renderCard();
    expect(await screen.findByText("该范围暂无经营数据")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "收入构成" })).not.toBeInTheDocument();
    first.unmount();

    server.use(http.get("/api/charts/1", () => HttpResponse.json({ detail: "failed" }, { status: 500 })));
    renderCard({ start: "2026-06-01", end: "2026-06-30" });
    expect(await screen.findByRole("button", { name: "重试经营分析" })).toBeInTheDocument();
  });

  it("does not label a recorded zero-revenue period as having no business data", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json(payload({
      kpis: { ...payload().kpis, total_revenue: 0, record_days: 1, open_days: 1 },
      income_summary: { daily_ledger_revenue: 0, confirmed_settlement_income: 0, total_income: 0, includes_settlement_income: false },
      daily: [{ date: "2026-07-01", revenue: 0, is_open: "营业" }], categories: [], excluded_categories: [],
    }))));
    renderCard();
    await screen.findByRole("region", { name: "营业日历" });
    expect(screen.queryByText("该范围暂无经营数据")).not.toBeInTheDocument();
  });

  it("uses income shading without a resident calendar amount and preserves the exact reading", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json(payload({ daily: [{ date: "2026-07-01", revenue: 9999999999, is_open: "营业" }] }))));
    renderCard();
    const date = await screen.findByRole("button", { name: "2026-07-01 营业 €9.999.999.999" });
    expect(date).toHaveTextContent(/^1营业$/);
    expect(date).toHaveAttribute("style", "background-color: color-mix(in oklab, var(--primary) 20%, transparent);");
    expect(screen.getByRole("status", { name: "日历读数" })).toHaveTextContent("€9.999.999.999");
  });

  it("keeps cached content visible and labels a failed refresh", async () => {
    let fail = false;
    server.use(http.get("/api/charts/1", () => fail ? HttpResponse.json({ detail: "failed" }, { status: 500 }) : HttpResponse.json(payload())));
    const { client } = renderCard();

    expect((await screen.findAllByText("€100")).length).toBeGreaterThan(0);
    fail = true;
    await client.invalidateQueries({ queryKey: ["charts", 1] });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("刷新经营分析失败，当前显示上次取得的数据。"));
    expect(screen.getAllByText("€100").length).toBeGreaterThan(0);
  });

  it("avoids a numeric comparison when the prior total is zero", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json({ ...payload(), period_coverage: { start: "2026-07-01", end: "2026-07-17", record_days: 2, interval_days: 17 }, ledger_comparison: { current_revenue: 100, previous_revenue: 0, change_percent: null, status: "zero_previous", short_previous_month: false } })));
    renderCard();

    expect(await screen.findByText("上期每日台账营业额为 0，不可比较增幅。")).toBeInTheDocument();
    expect(screen.queryByText(/Infinity|NaN/)).not.toBeInTheDocument();
  });

  it("offers a weekly calendar for the successful single-month scope and disables future and outside dates", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json({ ...payload(),
      range: { start: "2026-07-02", end: "2026-07-04", bucket: "day" },
      daily: [{ date: "2026-07-03", revenue: 0, is_open: "休息" }, { date: "2026-07-04", revenue: 0, is_open: "营业" }],
    })));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><BusinessAnalysisCard storeId={1} range={{ start: "2026-07-02", end: "2026-07-04" }} today="2026-07-04" /></QueryClientProvider>);
    expect(await screen.findByRole("region", { name: "营业日历" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2026-07-01 范围外" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "2026-07-02 未录入 —" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "2026-07-03 休息 €0" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "2026-07-04 营业 €0" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "2026-07-05 未来" })).toBeDisabled();
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
      classified_included_total: 420,
      categories: [
        { category_id: 1, category_name: "现金收入", amount: 300 },
        { category_id: null, category_name: "公司结算", amount: 120 },
      ],
    }))));
    renderCard();

    expect(await screen.findByText("日常营业额")).toBeInTheDocument();
    expect(screen.getByText("公司结算收入")).toBeInTheDocument();
    expect(screen.getByText("月度总收入")).toBeInTheDocument();
    expect(screen.getAllByText("€300")).toHaveLength(2);
    expect(screen.getAllByText("€120")).toHaveLength(2);
    expect(screen.getByText("€420")).toBeInTheDocument();
    expect(screen.getByLabelText("收入分类")).toHaveTextContent("公司结算");
    expect(screen.getByLabelText("公司结算 占比 28.6%")).toBeInTheDocument();
  });

  it("reads short-month limits without inventing an earlier date and omits calendars for cross-month scopes", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json({ ...payload(),
      range: { start: "2026-03-01", end: "2026-03-31", bucket: "day" },
      comparison_daily: [{ date: "2026-02-28", revenue: 80, is_open: "营业" }],
      period_coverage: { start: "2026-03-01", end: "2026-03-31", record_days: 1, interval_days: 31 },
      comparison_coverage: { start: "2026-02-01", end: "2026-02-28", record_days: 1, interval_days: 28 },
      ledger_comparison: { current_revenue: 100, previous_revenue: 80, change_percent: 25, status: "comparable", short_previous_month: true },
    })));
    const first = renderCard({ start: "2026-03-01", end: "2026-03-31" });
    expect(await screen.findByText("本期已记录 1 / 31 天；上期已记录 1 / 28 天")).toBeInTheDocument();
    expect(screen.getByText(/上月较短/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("趋势读数日期"), { target: { value: "2026-03-31" } });
    expect(screen.getByRole("status", { name: "趋势读数" })).toHaveTextContent("上期无对应日期");
    first.unmount();
    server.use(http.get("/api/charts/1", () => HttpResponse.json({ ...payload(), range: { start: "2026-01-01", end: "2026-03-31", bucket: "month" } })));
    renderCard({ start: "2026-01-01", end: "2026-03-31" });
    await screen.findByText("月度总收入趋势");
    expect(screen.getByText("月粒度：月度总收入，包含开票月份已确认公司结算。")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "营业日历" })).not.toBeInTheDocument();
  });

  it("waits through automatic retries before a failed first request and recovers without a fake missing calendar", async () => {
    let fail = true;
    let requests = 0;
    server.use(http.get("/api/charts/1", () => { requests += 1; return fail ? HttpResponse.json({ detail: "offline" }, { status: 503 }) : HttpResponse.json(payload()); }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: 2, retryDelay: 1 } } });
    render(<QueryClientProvider client={client}><BusinessAnalysisCard storeId={1} range={{ start: "2026-07-01", end: "2026-07-17" }} /></QueryClientProvider>);
    expect(await screen.findByRole("button", { name: "重试经营分析" })).toBeInTheDocument();
    expect(requests).toBe(3);
    expect(screen.queryByRole("region", { name: "营业日历" })).not.toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "重试经营分析" }));
    expect(await screen.findByRole("region", { name: "营业日历" })).toBeInTheDocument();
  });
});
