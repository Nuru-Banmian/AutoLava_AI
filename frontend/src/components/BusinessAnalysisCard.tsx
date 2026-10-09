import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { ChartsResponse } from "@/api/types";
import { ChartPanel } from "@/components/ChartPanel";
import { DailyLedgerTrend } from "@/components/DailyLedgerTrend";
import { BusinessCalendar } from "@/components/BusinessCalendar";
import { IncomeComposition } from "@/components/IncomeComposition";
import { GroupedPerformanceCharts } from "@/components/GroupedPerformanceCharts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { analysisRange, analysisSearchParams, type DateRange } from "@/lib/business-record-ranges";
import { chartsKey, formatWholeEuro } from "@/lib/user-api";

interface BusinessAnalysisCardProps {
  storeId: number;
  range: DateRange;
  today?: string;
  onSelectDate?: (date: string) => void;
  visible?: boolean;
}

function comparisonText(data: ChartsResponse): string | null {
  const previous = data.comparison_kpis;
  if (!previous) return null;
  if (data.period_coverage?.statistical_days === 0 && data.income_summary.confirmed_settlement_income === 0) return "本期无已统计收入，不可比较增幅";
  if (data.comparison_coverage?.statistical_days === 0 && previous.total_revenue === 0) return "上期无已统计收入，不可比较增幅";

  const current = data.kpis.total_revenue;
  const previousTotal = previous.total_revenue;
  if (previousTotal === 0) return "上期为 0，暂无可比增幅";

  const deltaTenths = Math.trunc(((current - previousTotal) * 1000) / previousTotal);
  const absoluteTenths = Math.abs(deltaTenths);
  const prefix = deltaTenths > 0 ? "+" : deltaTenths < 0 ? "-" : "";
  return `较上期 ${prefix}${Math.floor(absoluteTenths / 10)}.${absoluteTenths % 10}%`;
}

function Kpi({ title, value }: { title: string; value: string }) {
  return <div className="rounded-lg bg-muted/50 p-2.5">
    <p className="text-sm text-muted-foreground">{title}</p>
    <strong className="text-lg tabular-nums">{value}</strong>
  </div>;
}

export function BusinessAnalysisCard({ storeId, range, today = range.end, onSelectDate, visible = true }: BusinessAnalysisCardProps) {
  const resolved = useMemo(() => {
    try {
      return analysisRange("custom", range.end, range);
    } catch {
      return null;
    }
  }, [range.end, range.start]);
  const queryString = resolved ? analysisSearchParams(resolved).toString() : "invalid";
  const charts = useQuery({
    queryKey: chartsKey(storeId, queryString),
    enabled: resolved !== null,
    queryFn: ({ signal }) => api<ChartsResponse>(`/charts/${storeId}?${queryString}`, { signal }),
  });
  const data = visible ? charts.data : undefined;
  const hasStatisticalLedger = data?.period_coverage?.statistical_days !== 0;
  const trend = data ? (data.range.bucket === "day"
    ? data.daily.map((row) => ({ label: row.date, revenue: row.revenue }))
    : data.monthly.map((row) => ({ label: row.month, revenue: row.monthly_total_income }))) : [];
  const hasBusinessData = (hasStatisticalLedger && (data?.kpis.record_days ?? 0) > 0) || (data?.income_summary.confirmed_settlement_income ?? 0) !== 0;
  const isSingleMonth = data?.range.start.slice(0, 7) === data?.range.end.slice(0, 7);

  return <Card>
    <CardHeader className="px-3 py-3 sm:px-4 sm:py-3">
      <CardTitle>经营分析</CardTitle>
    </CardHeader>
    <CardContent className="grid gap-3 px-3 pb-3 sm:px-4 sm:pb-4">
      {!resolved && <p role="alert">请选择有效的日期范围</p>}
      {charts.isLoading && !data && <p role="status">加载经营分析…</p>}
      {charts.error && !data && <div role="alert" className="flex items-center gap-3"><span>经营分析加载失败</span><Button type="button" size="sm" variant="outline" onClick={() => void charts.refetch()}>重试经营分析</Button></div>}
      {charts.isFetching && data && !charts.isError && <p role="status">正在刷新经营分析…</p>}
      {charts.isRefetchError && data && <div role="alert" className="grid gap-2"><p>刷新经营分析失败，当前显示上次取得的数据。</p><Button type="button" className="w-fit" variant="outline" onClick={() => void charts.refetch()}>重试经营分析</Button></div>}
      {data && <>
        {data.income_summary.includes_settlement_income ? (
          <div className="grid min-w-0 gap-2 sm:grid-cols-3" aria-label="月度收入汇总" role="region">
            <Kpi title="日常营业额" value={formatWholeEuro(hasStatisticalLedger ? data.income_summary.daily_ledger_revenue : null)} />
            <Kpi title="已确认公司结算收入" value={formatWholeEuro(data.income_summary.confirmed_settlement_income)} />
            <Kpi title={isSingleMonth ? "月度总收入" : "月度总收入汇总"} value={formatWholeEuro(hasStatisticalLedger || data.income_summary.confirmed_settlement_income !== 0 ? data.income_summary.total_income : null)} />
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-3">
            <Kpi title="每日台账营业额" value={formatWholeEuro(hasStatisticalLedger ? data.income_summary.daily_ledger_revenue : null)} />
            <Kpi title="经营日" value={`${data.kpis.open_days} 天`} />
            <Kpi title="经营日均台账营业额" value={formatWholeEuro(data.kpis.open_days ? data.kpis.average_revenue : null)} />
          </div>
        )}
        <div className="grid gap-1 text-sm text-muted-foreground">
          <p>当前区间：{data.range.start} 至 {data.range.end}（按{data.range.bucket === "day" ? "日" : "月"}）</p>
          {data.period_coverage && <p>已统计 {data.period_coverage.statistical_days ?? data.kpis.record_days} 天；未统计 {data.period_coverage.unreported_days ?? 0} 天；未录入 {data.period_coverage.missing_record_days ?? data.period_coverage.interval_days - data.period_coverage.record_days} 天。金额仅为已知部分，集中清点不跨日分摊。</p>}
          {data.comparison_kpis && <p>比较区间：{data.comparison_kpis.start} 至 {data.comparison_kpis.end}</p>}
          {data.comparison_coverage && <p>比较期：已统计 {data.comparison_coverage.statistical_days} 天；未统计 {data.comparison_coverage.unreported_days} 天；未录入 {data.comparison_coverage.missing_record_days} 天。</p>}
          {data.range.bucket === "month" && comparisonText(data) && <p>{comparisonText(data)}</p>}
        </div>
        {!hasBusinessData && <p>该范围暂无经营数据</p>}
        {data.range.bucket === "day" ? <DailyLedgerTrend key={`trend-${data.range.start}-${data.range.end}`} data={data} /> : <ChartPanel embedded title="月度总收入趋势" kind="line" data={trend} xKey="label" valueKey="revenue" emptyMessage="暂无趋势数据" heightClassName="h-64 min-h-64" />}
        <GroupedPerformanceCharts key={`${storeId}:${data.range.start}:${data.range.end}`} data={data} />
        <div className={`grid min-w-0 items-stretch gap-3 ${isSingleMonth ? "lg:grid-cols-2 lg:grid-rows-[auto_1fr_auto]" : "lg:max-w-xl"}`}>
          <IncomeComposition key={`composition-${storeId}-${data.range.start}-${data.range.end}`} included={data.income_composition ?? []} excluded={data.excluded_categories} totalIncome={hasStatisticalLedger || data.income_summary.confirmed_settlement_income !== 0 ? data.income_summary.total_income : null} />
          {isSingleMonth && <BusinessCalendar key={`calendar-${data.range.start}-${data.range.end}`} data={data} today={today} onSelectDate={onSelectDate} />}
        </div>
      </>}
    </CardContent>
  </Card>;
}
