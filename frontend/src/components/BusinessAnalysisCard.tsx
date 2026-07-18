import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { ChartsResponse } from "@/api/types";
import { ChartPanel } from "@/components/ChartPanel";
import { IncomeComposition } from "@/components/IncomeComposition";
import { NativeDateInput } from "@/components/NativeDateInput";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { analysisRange, analysisSearchParams, type AnalysisRangeMode, type DateRange } from "@/lib/business-record-ranges";
import { amountToCents, chartNumber, formatMoney, chartsKey } from "@/lib/user-api";

interface BusinessAnalysisCardProps {
  storeId: number;
  today: string;
}

const rangeModes: { mode: AnalysisRangeMode; label: string }[] = [
  { mode: "current-month", label: "本月" },
  { mode: "previous-month", label: "上月" },
  { mode: "six-months", label: "近 6 月" },
  { mode: "custom", label: "自定义" },
];

function comparisonText(data: ChartsResponse): string | null {
  const previous = data.comparison_kpis;
  if (!previous) return null;

  const currentCents = amountToCents(data.kpis.total_revenue) ?? 0n;
  const previousCents = amountToCents(previous.total_revenue) ?? 0n;
  if (previousCents === 0n) return "上期为 0，暂无可比增幅";

  const deltaCents = currentCents - previousCents;
  const deltaTenths = (deltaCents * 1000n) / previousCents;
  const absoluteTenths = deltaTenths < 0n ? -deltaTenths : deltaTenths;
  const prefix = deltaTenths > 0n ? "+" : deltaTenths < 0n ? "-" : "";
  return `较上期 ${prefix}${absoluteTenths / 10n}.${absoluteTenths % 10n}%`;
}

function Kpi({ title, value }: { title: string; value: string }) {
  return <div className="rounded-lg bg-muted/50 p-3">
    <p className="text-sm text-muted-foreground">{title}</p>
    <strong className="text-xl tabular-nums">{value}</strong>
  </div>;
}

export function BusinessAnalysisCard({ storeId, today }: BusinessAnalysisCardProps) {
  const [mode, setMode] = useState<AnalysisRangeMode>("current-month");
  const [custom, setCustom] = useState<DateRange>(() => ({ start: `${today.slice(0, 7)}-01`, end: today }));
  const resolved = useMemo(() => {
    try {
      return analysisRange(mode, today, custom);
    } catch {
      return null;
    }
  }, [mode, today, custom]);
  const queryString = resolved ? analysisSearchParams(resolved).toString() : "invalid";
  const charts = useQuery({
    queryKey: chartsKey(storeId, queryString),
    enabled: resolved !== null,
    queryFn: () => api<ChartsResponse>(`/charts/${storeId}?${queryString}`),
  });
  const data = charts.data;
  const trend = data ? (data.range.bucket === "day"
    ? data.daily.map((row) => ({ label: row.date, revenue: chartNumber(row.revenue), revenue_raw: row.revenue }))
    : data.monthly.map((row) => ({ label: row.month, revenue: chartNumber(row.revenue), revenue_raw: row.revenue }))) : [];
  const hasBusinessData = (amountToCents(data?.kpis.total_revenue ?? "0") ?? 0n) !== 0n;

  return <Card>
    <CardHeader className="gap-4">
      <CardTitle>经营分析</CardTitle>
      <div className="flex flex-wrap gap-2" aria-label="经营分析日期范围">
        {rangeModes.map(({ mode: nextMode, label }) => <Button key={nextMode} type="button" variant={mode === nextMode ? "default" : "outline"} size="sm" aria-pressed={mode === nextMode} onClick={() => setMode(nextMode)}>{label}</Button>)}
      </div>
      {mode === "custom" && <div className="flex flex-wrap gap-3">
        <label className="grid gap-1 text-sm">开始日期<NativeDateInput aria-label="分析开始日期" value={custom.start} max={custom.end || today} onChange={(event) => setCustom((value) => ({ ...value, start: event.target.value }))} /></label>
        <label className="grid gap-1 text-sm">结束日期<NativeDateInput aria-label="分析结束日期" value={custom.end} min={custom.start} max={today} onChange={(event) => setCustom((value) => ({ ...value, end: event.target.value }))} /></label>
      </div>}
    </CardHeader>
    <CardContent className="grid gap-5">
      {!resolved && <p role="alert">请选择有效的日期范围</p>}
      {charts.isLoading && !data && <p role="status">加载经营分析…</p>}
      {charts.error && !data && <div role="alert" className="flex items-center gap-3"><span>经营分析加载失败</span><Button type="button" size="sm" variant="outline" onClick={() => void charts.refetch()}>重试经营分析</Button></div>}
      {charts.isRefetchError && data && <p role="alert">刷新失败</p>}
      {data && <>
        <div className="grid gap-2 sm:grid-cols-3">
          <Kpi title="总营业额" value={formatMoney(data.kpis.total_revenue)} />
          <Kpi title="营业天数" value={`${data.kpis.open_days} 天`} />
          <Kpi title="营业日均" value={formatMoney(data.kpis.average_revenue)} />
        </div>
        <div className="grid gap-1 text-sm text-muted-foreground">
          <p>当前区间：{data.range.start} 至 {data.range.end}（按{data.range.bucket === "day" ? "日" : "月"}）</p>
          {data.comparison_kpis && <p>比较区间：{data.comparison_kpis.start} 至 {data.comparison_kpis.end}</p>}
          {comparisonText(data) && <p>{comparisonText(data)}</p>}
        </div>
        {!hasBusinessData && <p>该范围暂无经营数据</p>}
        <ChartPanel embedded title="营业额趋势" kind="line" data={trend} xKey="label" valueKey="revenue" emptyMessage="暂无趋势数据" />
        <IncomeComposition included={data.categories} excluded={data.excluded_categories} classifiedIncludedTotal={data.classified_included_total} totalRevenue={data.kpis.total_revenue} />
      </>}
    </CardContent>
  </Card>;
}
