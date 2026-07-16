import { useQuery } from "@tanstack/react-query";
import { format, parseISO, subDays } from "date-fns";
import { useEffect, useMemo, useState } from "react";

import { api } from "@/api/client";
import type { ChartsResponse } from "@/api/types";
import { ChartPanel } from "@/components/ChartPanel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { chartNumber, chartsKey, money, storeLocalToday } from "@/lib/user-api";
import { useStore } from "@/stores/StoreProvider";

type RangeMode = "week" | "month" | "custom";

function monthRange(today: string) {
  return [`${today.slice(0, 7)}-01`, today] as const;
}

function weekRange(today: string) {
  return [format(subDays(parseISO(today), 6), "yyyy-MM-dd"), today] as const;
}

export function ChartsPage() {
  const { selected } = useStore();
  const today = selected ? storeLocalToday(selected) : "";
  const defaults = monthRange(today);
  const [mode, setMode] = useState<RangeMode>("month");
  const [start, setStart] = useState<string>(defaults[0]);
  const [end, setEnd] = useState<string>(defaults[1]);

  useEffect(() => {
    const next = monthRange(today);
    setMode("month");
    setStart(next[0]);
    setEnd(next[1]);
  }, [selected?.id, today]);

  const params = useMemo(() => new URLSearchParams({ start, end }).toString(), [start, end]);
  const charts = useQuery({
    queryKey: selected ? chartsKey(selected.id, params) : ["charts", "none"],
    enabled: Boolean(selected && start && end),
    queryFn: () => api<ChartsResponse>(`/charts/${selected!.id}?${params}`),
  });

  if (!selected) {
    return <section><h1 className="text-2xl font-semibold">营业分析</h1><p role="status">请先选择门店。</p></section>;
  }

  function selectPreset(nextMode: Exclude<RangeMode, "custom">) {
    const [nextStart, nextEnd] = nextMode === "week" ? weekRange(today) : monthRange(today);
    setMode(nextMode);
    setStart(nextStart);
    setEnd(nextEnd);
  }

  const data = charts.data;
  return (
    <section className="grid gap-5">
      <div>
        <h1 className="text-2xl font-semibold">营业分析</h1>
        <p className="mt-1 text-sm text-muted-foreground">查看营业额趋势和收入构成</p>
      </div>

      <div className="flex flex-wrap gap-2" aria-label="分析日期范围">
        <button className="rounded-lg border bg-card px-4 py-2 text-sm aria-pressed:border-primary aria-pressed:bg-primary aria-pressed:text-primary-foreground" aria-pressed={mode === "week"} onClick={() => selectPreset("week")}>最近 7 天</button>
        <button className="rounded-lg border bg-card px-4 py-2 text-sm aria-pressed:border-primary aria-pressed:bg-primary aria-pressed:text-primary-foreground" aria-pressed={mode === "month"} onClick={() => selectPreset("month")}>本月</button>
        <button className="rounded-lg border bg-card px-4 py-2 text-sm aria-pressed:border-primary aria-pressed:bg-primary aria-pressed:text-primary-foreground" aria-pressed={mode === "custom"} onClick={() => setMode("custom")}>自定义日期</button>
      </div>

      {mode === "custom" && (
        <div className="flex flex-wrap gap-4 rounded-xl border bg-card p-4">
          <label className="text-sm">开始日期<input aria-label="图表开始日期" type="date" value={start} max={end} onChange={(event) => setStart(event.target.value)} className="ml-2 rounded-lg border bg-background p-2" /></label>
          <label className="text-sm">结束日期<input aria-label="图表结束日期" type="date" value={end} min={start} max={today} onChange={(event) => setEnd(event.target.value)} className="ml-2 rounded-lg border bg-background p-2" /></label>
        </div>
      )}

      {charts.isLoading ? <p role="status">加载分析数据…</p> : charts.error ? <div role="alert"><span>{charts.error.message}</span><button className="ml-2 underline" onClick={() => void charts.refetch()}>重试</button></div> : data && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <KpiCard title="总营业额" value={money(data.kpis.total_revenue)} />
            <KpiCard title="营业天数" value={`${data.kpis.open_days} 天`} />
            <KpiCard title="平均营业额" value={money(data.kpis.average_revenue)} />
          </div>
          <ChartPanel
            title="营业额趋势"
            kind="line"
            data={data.daily.map((item) => ({ ...item, revenue: chartNumber(item.revenue), revenue_raw: item.revenue }))}
            xKey="date"
            valueKey="revenue"
          />
          {data.categories.length > 1 && (
            <ChartPanel
              title="收入构成"
              kind="horizontal-bar"
              data={data.categories.map((item) => ({ name: item.category_name, amount: chartNumber(item.amount), amount_raw: item.amount }))}
              xKey="name"
              valueKey="amount"
            />
          )}
        </>
      )}
    </section>
  );
}

function KpiCard({ title, value }: { title: string; value: string }) {
  return <Card><CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle></CardHeader><CardContent><strong className="text-2xl">{value}</strong></CardContent></Card>;
}
