import { useEffect, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { friendlyApiError } from "@/api/client";
import type { components } from "@/api/generated";
import { currentSessionScope } from "@/auth/sessionScope";
import { Button } from "@/components/ui/button";
import { useChartCache } from "./AgentChartCache";

type Descriptor = components["schemas"]["ChartDescriptor"];
type Snapshot = components["schemas"]["ChatChart"];
const colors = ["#2563eb", "#c2410c", "#15803d", "#7e22ce", "#0e7490", "#be185d"];
const granularities: Record<string, string> = { day: "逐日", week: "逐周", month: "逐月", year: "逐年" };
const statuses: Record<string, string> = {
  available: "已统计", no_statistical_ledger: "无已统计台账", no_operating_days: "无经营日",
  wash_count_disabled: "数量记录已关闭", no_wash_count: "数量未记录", zero_wash_count: "数量基期为零",
  no_valid_dates: "无有效日期", unknown: "未知", not_applicable: "不适用",
};
const coverageLabels: Record<string, string> = {
  interval_days: "区间天数", record_days: "已录入天数", missing_record_days: "未录入天数",
  operating_days: "经营天数", rest_days: "休息天数", unreported_days: "未统计天数",
  unreported_record_days: "未统计天数", statistical_record_days: "已统计天数",
  wash_count_covered_days: "数量已记录天数", wash_count_missing_operating_days: "数量缺失经营天数",
};

export function AgentChart({ storeId, messageId, description }: { storeId: number; messageId: number; description: Descriptor }) {
  const element = useRef<HTMLDivElement>(null);
  const cache = useChartCache();
  const [near, setNear] = useState(typeof IntersectionObserver === "undefined");
  const [visible, setVisible] = useState(typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const nearby = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) setNear(true); }, { rootMargin: "600px 0px" });
    const viewport = new IntersectionObserver(entries => setVisible(entries.some(e => e.isIntersecting)));
    if (element.current) { nearby.observe(element.current); viewport.observe(element.current); }
    return () => { nearby.disconnect(); viewport.disconnect(); };
  }, []);
  return <div ref={element} className="mt-4 min-w-0" style={{ height: 620, overflow: "auto" }} data-chart-id={description.chart_id}>
    {near ? <LoadedChart key={`${currentSessionScope()}:${storeId}:${messageId}:${description.chart_id}`} storeId={storeId} messageId={messageId} description={description} visible={visible} cache={cache} />
      : <div role="status" className="rounded-lg border p-3">图表等待进入附近区域：{description.title}</div>}
  </div>;
}

function LoadedChart({ storeId, messageId, description, visible, cache }: {
  storeId: number; messageId: number; description: Descriptor; visible: boolean; cache: ReturnType<typeof useChartCache>;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => {
    let active = true;
    const session = currentSessionScope();
    setSnapshot(null); setError(""); setSelected(null);
    void cache.read(storeId, messageId, description.chart_id).then((value) => {
      if (active && session === currentSessionScope() && value.chart_id === description.chart_id && value.message_id === messageId) setSnapshot(value);
    }).catch((cause) => {
      if (active && session === currentSessionScope()) setError(friendlyApiError(cause, "图表读取失败"));
    });
    return () => { active = false; };
  }, [storeId, messageId, description.chart_id, retry, cache]);
  if (error) return <div role="alert">{error} <Button variant="outline" onClick={() => setRetry((value) => value + 1)}>重试图表</Button></div>;
  if (!snapshot) return <div role="status" className="min-h-64">正在读取图表：{description.title}</div>;
  if (!visible) return <div role="status" className="rounded-lg border p-3">图表已读取，进入可见区域时绘制：{description.title}</div>;
  const chart = snapshot.payload;
  const point = selected === null ? null : chart.points[selected];
  const horizontal = chart.type === "horizontal_bar";
  const Chart = chart.type === "line" ? LineChart : BarChart;
  const dimensionLabel = ["category", "weather", "weekday"].includes(chart.dimension) ? "分类" : "日期";
  const selectPoint = (event: { activeTooltipIndex?: string | number | null }) => {
    if (event.activeTooltipIndex !== null && event.activeTooltipIndex !== undefined) setSelected(Number(event.activeTooltipIndex));
  };
  return <figure className="mt-4 min-w-0 rounded-lg border p-3" aria-label={chart.title}>
    <figcaption className="font-semibold">{chart.title}</figcaption>
    <p className="text-xs text-muted-foreground">{chart.range.start} 至 {chart.range.end} · {granularities[chart.granularity] ?? chart.granularity} · {chart.unit}</p>
    {chart.segment && <p className="text-xs text-muted-foreground">总范围：{chart.segment.total_range.start} 至 {chart.segment.total_range.end} · 第 {chart.segment.index}/{chart.segment.count} 段 · 各段纵轴一致</p>}
    {chart.unfinished && <p className="text-xs text-muted-foreground">当前周期尚未结束，仅统计至查询日。</p>}
    <div className="w-full" style={{ height: horizontal ? Math.max(288, chart.points.length * 32) : 288 }} aria-label={`${chart.title}趋势图`}>
      <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 600, height: 288 }}>
        <Chart data={chart.points} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 10, right: 15, bottom: 10, left: 0 }}
          onMouseMove={selectPoint} onClick={selectPoint}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={horizontal ? undefined : "dimension"} type={horizontal ? "number" : "category"}
            domain={horizontal ? chart.y_domain ?? ["auto", "auto"] : undefined} minTickGap={35} />
          <YAxis dataKey={horizontal ? "dimension" : undefined} type={horizontal ? "category" : "number"}
            domain={horizontal ? undefined : chart.y_domain ?? ["auto", "auto"]} width={horizontal ? 100 : 60} />
          <Tooltip content={() => point ? <div className="rounded border bg-card p-2 text-sm">
            <p>{point.dimension} · {point.state}</p>
            {chart.series.map((series) => <p key={series.key}>{series.label}：{point.values[series.key]?.exact ?? "未知"} {chart.unit} · {statuses[point.values[series.key]?.status ?? "unknown"] ?? "不可用"}</p>)}
          </div> : null} />
          <Legend />
          {chart.series.map((series, index) => chart.type === "line" ? <Line key={series.key} name={series.label}
            dataKey={(item) => item.values[series.key]?.plot ?? null} stroke={colors[index]}
            connectNulls={false} dot={{ r: 3 }} isAnimationActive={false} /> : <Bar key={series.key} name={series.label}
            dataKey={(item) => item.values[series.key]?.plot ?? null} fill={colors[index]}
            stackId={chart.type === "stacked_bar" ? "income" : undefined} isAnimationActive={false}
            onClick={(_, pointIndex) => setSelected(pointIndex)} />)}
        </Chart>
      </ResponsiveContainer>
    </div>
    <label className="flex items-center gap-2 text-sm">查看{dimensionLabel}
      <select aria-label={`${chart.title}查看${dimensionLabel}`} value={selected ?? ""}
        onChange={(event) => setSelected(event.target.value === "" ? null : Number(event.target.value))}
        className="min-w-0 rounded border bg-card p-1">
        <option value="">请选择或点选图表</option>
        {chart.points.map((item, index) => <option key={index} value={index}>{item.dimension}</option>)}
      </select>
    </label>
    <div className="mt-2 min-h-16 text-sm" role="status" aria-label="图表数据" aria-live="polite">
      {point ? <><p>{point.dimension} · {point.state}</p>{chart.series.map((series) => {
        const value = point.values[series.key];
        return <p key={series.key}>{series.label}：{value?.exact ?? "未知"} {value?.exact != null ? chart.unit : ""} · {statuses[value?.status ?? "unknown"] ?? "不可用"}</p>;
      })}</> : <p>悬浮或点选{dimensionLabel}查看准确值与状态。</p>}
    </div>
    <p className="text-xs text-muted-foreground">查询时间：{chart.queried_at} · 历史快照</p>
    {chart.notes.map((note, index) => <p key={index} className="text-xs text-muted-foreground">{note}</p>)}
    <p className="break-words text-xs text-muted-foreground">覆盖：{Object.entries(chart.coverage)
      .filter(([key, value]) => key in coverageLabels && typeof value === "number")
      .map(([key, value]) => `${coverageLabels[key]} ${value}`).join("；") || "暂无可统计覆盖"}</p>
  </figure>;
}
