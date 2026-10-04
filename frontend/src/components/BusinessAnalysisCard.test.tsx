import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    income_composition: [{ category_id: 1, category_name: "现金收入", amount: 100 }],
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
  it("compares operating-day samples in fixed weekday and weather order with missing weekdays distinct from zero", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json({ ...payload(),
      weekday: [
        { weekday: 4, average_revenue: 0, operating_day_count: 1 },
        { weekday: 0, average_revenue: 101, operating_day_count: 2 },
      ],
      weather: [
        { weather: "未记录", average_revenue: 80, operating_day_count: 3 },
        { weather: "历史未规范天气", average_revenue: 20, operating_day_count: 1 },
        { weather: "雷雨伴大冰雹", average_revenue: 200, operating_day_count: 1 },
        { weather: "兼容类别", average_revenue: 42, operating_day_count: 2 },
        { weather: "少云", average_revenue: 0, operating_day_count: 1 },
        { weather: "晴", average_revenue: 101, operating_day_count: 2 },
        { weather: "阴", average_revenue: 0, operating_day_count: 0 },
      ],
    })));
    renderCard();
    const weekday = await screen.findByRole("region", { name: "星期经营表现" });
    expect(within(weekday).getAllByRole("listitem").map((row) => row.textContent)).toEqual([
      "周一€1012 天", "周二—0 天", "周三—0 天", "周四—0 天", "周五€01 天", "周六—0 天", "周日—0 天",
    ]);
    const weather = screen.getByRole("region", { name: "天气与营业额对比" });
    expect(within(weather).getAllByRole("listitem").map((row) => row.textContent)).toEqual([
      "晴€1012 天", "少云€01 天", "雷雨伴大冰雹€2001 天", "兼容类别€422 天", "历史未规范天气€201 天", "未记录€803 天",
    ]);
    within(weekday).getByRole("listitem", { name: "周二：无经营日样本，—，0 天" }).focus();
    expect(within(weekday).getByRole("listitem", { name: "周二：无经营日样本，—，0 天" })).toHaveFocus();
    expect(within(weekday).queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(weather).queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByText("未记录仅表示经营日缺少记录天气，金额和样本仍计入。")).not.toBeInTheDocument();
  });
  it("keeps all canonical weather groups in the agreed order regardless of API order or preview preferences", async () => {
    const weatherNames = ["晴", "少云", "多云", "阴", "雾", "冻雾", "小毛毛雨", "毛毛雨", "大毛毛雨", "小冻毛毛雨", "冻毛毛雨", "小雨", "中雨", "大雨", "小冻雨", "冻雨", "小雪", "中雪", "大雪", "雪粒", "小阵雨", "阵雨", "大阵雨", "小阵雪", "大阵雪", "雷雨", "雷雨伴小冰雹", "雷雨伴大冰雹"];
    localStorage.setItem("weatherOrder", JSON.stringify(["雷雨伴大冰雹", "晴"]));
    server.use(http.get("/api/charts/1", () => HttpResponse.json({ ...payload(),
      weather: weatherNames.slice().reverse().map((weather, index) => ({ weather, average_revenue: index, operating_day_count: index + 1 })),
    })));
    renderCard();
    const weather = await screen.findByRole("region", { name: "天气与营业额对比" });
    expect(within(weather).getAllByRole("listitem").map((row) => row.getAttribute("aria-label")!.split("：")[0])).toEqual(weatherNames);
    expect(within(weather).queryByText("未记录")).not.toBeInTheDocument();
    expect(within(weather).queryByRole("combobox")).not.toBeInTheDocument();
    localStorage.removeItem("weatherOrder");
  });
  it("keeps the ledger comparison without redundant coverage or reading controls", async () => {
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
    await screen.findByText("每日台账营业额较上期 +25.0%");
    expect(screen.queryByText(/本期已记录/)).not.toBeInTheDocument();
    expect(screen.queryByText(/上期有效范围/)).not.toBeInTheDocument();
    expect(screen.queryByText("记录覆盖不完整，比较仅反映已记录每日台账。")).not.toBeInTheDocument();
    expect(screen.getByText("每日台账营业额较上期 +25.0%")).toBeInTheDocument();
    expect(screen.queryByLabelText("趋势读数日期")).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "趋势读数" })).not.toBeInTheDocument();
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
    expect(screen.getByTestId("chart-panel-plot")).toHaveClass("h-48", "min-h-48");
    expect(requests[0].pathname + requests[0].search).toBe("/api/charts/1?start=2026-07-01&end=2026-07-17&bucket=day");
    expect(requests).toHaveLength(1);
    expect(screen.queryByLabelText("经营分析日期范围")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("分析开始日期")).not.toBeInTheDocument();
    expect(screen.getByText("比较区间：2026-06-01 至 2026-06-17")).toBeInTheDocument();
    expect(screen.getByText(/^当前区间：.*（按日）$/)).toBeInTheDocument();
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
    expect(screen.getByRole("region", { name: "收入构成" })).toHaveTextContent("暂无收入构成");
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

  it("uses revenue shading in theme blue and preserves the exact reading", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json(payload({ daily: [{ date: "2026-07-01", revenue: 9999999999, is_open: "营业" }] }))));
    renderCard();
    const date = await screen.findByRole("button", { name: "2026-07-01 营业 €9.999.999.999" });
    expect(date).toHaveTextContent(/^1€9\.999\.999\.999营业$/);
    expect(date).toHaveClass("bg-blue-200", "text-blue-950");
    expect(screen.getByLabelText("营业额颜色图例")).toHaveTextContent("€0–€9.999.999.999");
    expect(date).toHaveAttribute("title", "2026-07-01 营业 €9.999.999.999");
    expect(screen.queryByLabelText("日历读数日期")).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "日历读数" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^查看 .* 每日台账$/ })).not.toBeInTheDocument();
  });

  it("keeps cached content visible and labels a failed refresh", async () => {
    let fail = false;
    server.use(http.get("/api/charts/1", () => fail ? HttpResponse.json({ detail: "failed" }, { status: 500 }) : HttpResponse.json({ ...payload(),
      weekday: [{ weekday: 0, average_revenue: 77, operating_day_count: 2 }],
      weather: [{ weather: "晴", average_revenue: 77, operating_day_count: 2 }],
    })));
    const { client } = renderCard();

    expect((await screen.findAllByText("€100")).length).toBeGreaterThan(0);
    fail = true;
    await client.invalidateQueries({ queryKey: ["charts", 1] });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("刷新经营分析失败，当前显示上次取得的数据。"));
    expect(screen.getAllByText("€100").length).toBeGreaterThan(0);
    expect(screen.getByRole("listitem", { name: "晴：€77，2 天经营日样本" })).toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: "2026-07-02 未录入 —" })).toHaveClass("bg-amber-50", "border-dashed");
    expect(screen.getByRole("button", { name: "2026-07-03 休息 €0" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "2026-07-03 休息 €0" })).toHaveClass("bg-slate-200");
    expect(screen.getByRole("button", { name: "2026-07-04 营业 €0" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "2026-07-04 营业 €0" })).toHaveAttribute("aria-current", "date");
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
      income_composition: [
        { category_id: 1, category_name: "现金收入", amount: 300 },
        { category_id: null, category_name: "公司结算", amount: 120 },
      ],
      categories: [
        { category_id: 1, category_name: "现金收入", amount: 300 },
        { category_id: null, category_name: "公司结算", amount: 120 },
      ],
    }))));
    renderCard();

    expect(await screen.findByText("日常营业额")).toBeInTheDocument();
    expect(screen.getByText("已确认公司结算收入")).toBeInTheDocument();
    expect(screen.getByText("月度总收入")).toBeInTheDocument();
    expect(screen.getAllByText("€300")).toHaveLength(2);
    expect(screen.getAllByText("€120")).toHaveLength(2);
    expect(screen.getAllByText("€420")).toHaveLength(2);
    expect(screen.getByLabelText("收入分类")).toHaveTextContent("公司结算");
    expect(screen.getByLabelText("公司结算 占比 28.6%")).toBeInTheDocument();
  });

  it("omits short-month explanations and calendars for cross-month scopes", async () => {
    server.use(http.get("/api/charts/1", () => HttpResponse.json({ ...payload(),
      range: { start: "2026-03-01", end: "2026-03-31", bucket: "day" },
      comparison_daily: [{ date: "2026-02-28", revenue: 80, is_open: "营业" }],
      period_coverage: { start: "2026-03-01", end: "2026-03-31", record_days: 1, interval_days: 31 },
      comparison_coverage: { start: "2026-02-01", end: "2026-02-28", record_days: 1, interval_days: 28 },
      ledger_comparison: { current_revenue: 100, previous_revenue: 80, change_percent: 25, status: "comparable", short_previous_month: true },
    })));
    const first = renderCard({ start: "2026-03-01", end: "2026-03-31" });
    await screen.findByText("每日台账营业额较上期 +25.0%");
    expect(screen.queryByText(/本期已记录/)).not.toBeInTheDocument();
    expect(screen.queryByText(/上期有效范围/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("趋势读数日期")).not.toBeInTheDocument();
    first.unmount();
    server.use(http.get("/api/charts/1", () => HttpResponse.json({ ...payload(), range: { start: "2026-01-01", end: "2026-03-31", bucket: "month" } })));
    renderCard({ start: "2026-01-01", end: "2026-03-31" });
    await screen.findByText("月度总收入趋势");
    expect(screen.queryByText("月粒度：月度总收入，包含开票月份已确认公司结算。")).not.toBeInTheDocument();
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
    expect(screen.queryByRole("region", { name: "星期经营表现" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "天气与营业额对比" })).not.toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "重试经营分析" }));
    expect(await screen.findByRole("region", { name: "营业日历" })).toBeInTheDocument();
  });
  it("does not retain another store or range's groups when its late response arrives", async () => {
    let releaseOld!: () => void;
    const delayed = new Promise<void>((resolve) => { releaseOld = resolve; });
    let oldRequested = false;
    let oldReturned = false;
    server.use(http.get("/api/charts/:store", async ({ params, request }) => {
      const start = new URL(request.url).searchParams.get("start")!;
      if (params.store === "1" && start === "2026-07-01") {
        oldRequested = true;
        await delayed;
        oldReturned = true;
        return HttpResponse.json({ ...payload(), weather: [{ weather: "晴", average_revenue: 999, operating_day_count: 4 }] });
      }
      return HttpResponse.json({ ...payload(), range: { start, end: "2026-06-30", bucket: "day" },
        weather: [{ weather: "中雨", average_revenue: 42, operating_day_count: 1 }],
      });
    }));
    const { client, rerender } = renderCard();
    await waitFor(() => expect(oldRequested).toBe(true));
    rerender(<QueryClientProvider client={client}><BusinessAnalysisCard storeId={2} range={{ start: "2026-06-01", end: "2026-06-30" }} /></QueryClientProvider>);
    expect(screen.queryByRole("region", { name: "天气与营业额对比" })).not.toBeInTheDocument();
    expect(await screen.findByRole("listitem", { name: "中雨：€42，1 天经营日样本" })).toBeInTheDocument();
    releaseOld();
    await waitFor(() => expect(oldReturned).toBe(true));
    expect(screen.queryByRole("listitem", { name: "晴：€999，4 天经营日样本" })).not.toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "中雨：€42，1 天经营日样本" })).toBeInTheDocument();
  });
});
