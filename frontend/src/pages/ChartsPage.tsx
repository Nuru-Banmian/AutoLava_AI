import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import type { ChartsResponse, DatabaseResponse } from "@/api/types";
import { ChartPanel } from "@/components/ChartPanel";
import { categoryCatalogKey, chartsKey, money, storeLocalToday } from "@/lib/user-api";
import { useStore } from "@/stores/StoreProvider";
function monthRange(today: string) { return [`${today.slice(0, 7)}-01`, today] as const; }
const weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"];
export function ChartsPage() {
  const { selected } = useStore(); const today = selected ? storeLocalToday(selected) : ""; const defaults = monthRange(today);
  const [start, setStart] = useState<string>(defaults[0]); const [end, setEnd] = useState<string>(defaults[1]); const [selectedIds, setSelectedIds] = useState<number[] | null>(null);
  useEffect(() => { const next = monthRange(today); setStart(next[0]); setEnd(next[1]); setSelectedIds(null); }, [selected?.id, today]);
  const catalog = useQuery({ queryKey: selected ? categoryCatalogKey(selected.id, today) : ["categoryCatalog", "none"], enabled: Boolean(selected), queryFn: () => api<DatabaseResponse>(`/database/${selected!.id}/records?start=${today}&end=${today}&page=1&page_size=1`) });
  useEffect(() => { if (catalog.data && selectedIds === null) setSelectedIds(catalog.data.categories.filter((category) => category.include_in_total).map((category) => category.id)); }, [catalog.data, selectedIds]);
  const params = useMemo(() => { const query = new URLSearchParams({ start, end }); selectedIds?.forEach((id) => query.append("category_id", String(id))); return query.toString(); }, [start, end, selectedIds]);
  const charts = useQuery({ queryKey: selected ? chartsKey(selected.id, params) : ["charts", "none"], enabled: Boolean(selected && selectedIds?.length && start && end), queryFn: () => api<ChartsResponse>(`/charts/${selected!.id}?${params}`) });
  if (!selected) return <section><h1 className="text-2xl font-semibold">图表</h1><p role="status">请先选择门店。</p></section>;
  const data = charts.data;
  return <section className="grid gap-4"><h1 className="text-2xl font-semibold">图表</h1><div className="flex flex-wrap gap-4"><label>开始日期<input aria-label="图表开始日期" type="date" value={start} onChange={(e) => setStart(e.target.value)} className="ml-2 rounded border p-2" /></label><label>结束日期<input aria-label="图表结束日期" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="ml-2 rounded border p-2" /></label></div>
    <fieldset className="flex flex-wrap gap-3"><legend className="font-medium">收入分类</legend>{catalog.data?.categories.filter((c) => c.is_active).map((category) => <label key={category.id} className="flex items-center gap-1"><input type="checkbox" aria-label={category.name} checked={selectedIds?.includes(category.id) ?? false} onChange={(e) => setSelectedIds((old) => e.target.checked ? [...(old ?? []), category.id] : (old ?? []).filter((id) => id !== category.id))} />{category.name}</label>)}</fieldset>
    {selectedIds?.length === 0 && <p role="status">请至少选择一个收入分类。</p>}
    {charts.isLoading ? <p role="status">加载图表…</p> : charts.error ? <p role="alert">{charts.error.message}</p> : data && <><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div className="rounded border p-4"><h2>总收入</h2><strong>{money(data.kpis.total_revenue)}</strong></div><div className="rounded border p-4"><h2>记录天数</h2><strong>{data.kpis.record_days}</strong></div><div className="rounded border p-4"><h2>营业天数</h2><strong>{data.kpis.open_days}</strong></div>{data.kpis.total_wash_count !== null && <div className="rounded border p-4"><h2>洗车总数</h2><strong>{data.kpis.total_wash_count}</strong></div>}{data.kpis.average_ticket !== null && <div className="rounded border p-4"><h2>平均客单价</h2><strong>{money(data.kpis.average_ticket)}</strong></div>}</div>
      <div className="grid gap-4 lg:grid-cols-2"><ChartPanel title="主要收入分类"><div className="space-y-2">{data.kpis.primary_categories.length ? data.kpis.primary_categories.map((item) => <p key={item.category_id}>{item.category_name} {money(item.amount)}</p>) : <p>暂无数据</p>}</div></ChartPanel><ChartPanel title="每日营业额" kind="bar" data={data.daily.map((item) => ({ ...item, revenue: Number(item.revenue) }))} xKey="date" valueKey="revenue" /><ChartPanel title="收入构成" kind="pie" data={data.categories.map((item) => ({ name: item.category_name, amount: Number(item.amount) }))} xKey="name" valueKey="amount" /><ChartPanel title="月度趋势" kind="line" data={data.monthly.map((item) => ({ ...item, revenue: Number(item.revenue) }))} xKey="month" valueKey="revenue" /><ChartPanel title="天气表现" kind="bar" data={data.weather.map((item) => ({ ...item, average_revenue: Number(item.average_revenue) }))} xKey="weather" valueKey="average_revenue" /><ChartPanel title="星期表现" kind="bar" data={data.weekday.map((item) => ({ label: weekdays[item.weekday] ?? String(item.weekday), average_revenue: Number(item.average_revenue) }))} xKey="label" valueKey="average_revenue" /></div></>}
  </section>;
}
