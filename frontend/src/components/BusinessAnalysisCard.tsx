import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { ChartsResponse } from "@/api/types";
import { ChartPanel } from "@/components/ChartPanel";
import { IncomeComposition } from "@/components/IncomeComposition";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { analysisRange, analysisSearchParams, type DateRange } from "@/lib/business-record-ranges";
import { chartsKey, formatWholeEuro } from "@/lib/user-api";

interface BusinessAnalysisCardProps {
  storeId: number;
  range: DateRange;
}

function comparisonText(data: ChartsResponse): string | null {
  const previous = data.comparison_kpis;
  if (!previous) return null;

  const current = data.kpis.total_revenue;
  const previousTotal = previous.total_revenue;
  if (previousTotal === 0) return "上期为 0，暂无可比增幅";

  const deltaTenths = Math.trunc(((current - previousTotal) * 1000) / previousTotal);
  const absoluteTenths = Math.abs(deltaTenths);
  const prefix = deltaTenths > 0 ? "+" : deltaTenths < 0 ? "-" : "";
  return `较上期 ${prefix}${Math.floor(absoluteTenths / 10)}.${absoluteTenths % 10}%`;
}

function Kpi({ title, value }: { title: string; value: string }) {
  return <div className="rounded-lg bg-muted/50 p-3">
    <p className="text-sm text-muted-foreground">{title}</p>
    <strong className="text-xl tabular-nums">{value}</strong>
  </div>;
}

export function BusinessAnalysisCard({ storeId, range }: BusinessAnalysisCardProps) {
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
    queryFn: () => api<ChartsResponse>(`/charts/${storeId}?${queryString}`),
  });
  const data = charts.data;
  const trend = data ? (data.range.bucket === "day"
    ? data.daily.map((row) => ({ label: row.date, revenue: row.revenue }))
    : data.monthly.map((row) => ({ label: row.month, revenue: row.monthly_total_income }))) : [];
  const hasBusinessData = (data?.income_summary.total_income ?? 0) !== 0;
  const isSingleMonth = data?.range.start.slice(0, 7) === data?.range.end.slice(0, 7);

  return <Card>
    <CardHeader>
      <CardTitle>经营分析</CardTitle>
    </CardHeader>
    <CardContent className="grid gap-5">
      {!resolved && <p role="alert">请选择有效的日期范围</p>}
      {charts.isLoading && !data && <p role="status">加载经营分析…</p>}
      {charts.error && !data && <div role="alert" className="flex items-center gap-3"><span>经营分析加载失败</span><Button type="button" size="sm" variant="outline" onClick={() => void charts.refetch()}>重试经营分析</Button></div>}
      {charts.isRefetchError && data && <p role="alert">刷新失败</p>}
      {data && <>
        {data.income_summary.includes_settlement_income ? (
          <div className="grid min-w-0 gap-2 sm:grid-cols-3" aria-label="月度收入汇总" role="region">
            <Kpi title="日常营业额" value={formatWholeEuro(data.income_summary.daily_ledger_revenue)} />
            <Kpi title="公司结算收入" value={formatWholeEuro(data.income_summary.confirmed_settlement_income)} />
            <Kpi title={isSingleMonth ? "月度总收入" : "月度总收入汇总"} value={formatWholeEuro(data.income_summary.total_income)} />
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-3">
            <Kpi title="总营业额" value={formatWholeEuro(data.kpis.total_revenue)} />
            <Kpi title="营业天数" value={`${data.kpis.open_days} 天`} />
            <Kpi title="营业日均" value={formatWholeEuro(data.kpis.average_revenue)} />
          </div>
        )}
        <div className="grid gap-1 text-sm text-muted-foreground">
          <p>当前区间：{data.range.start} 至 {data.range.end}（按{data.range.bucket === "day" ? "日" : "月"}）</p>
          {data.comparison_kpis && <p>比较区间：{data.comparison_kpis.start} 至 {data.comparison_kpis.end}</p>}
          {comparisonText(data) && <p>{comparisonText(data)}</p>}
        </div>
        {!hasBusinessData && <p>该范围暂无经营数据</p>}
        <ChartPanel embedded title="营业额趋势" kind="line" data={trend} xKey="label" valueKey="revenue" emptyMessage="暂无趋势数据" heightClassName="h-64 min-h-64" />
        <IncomeComposition included={data.categories} excluded={data.excluded_categories} classifiedIncludedTotal={data.classified_included_total} />
      </>}
    </CardContent>
  </Card>;
}
