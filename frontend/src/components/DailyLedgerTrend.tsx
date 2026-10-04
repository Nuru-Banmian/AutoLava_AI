import { eachDayOfInterval, format, parseISO } from "date-fns";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { ChartsResponse } from "@/api/types";
import { formatCompactEuro } from "@/lib/compact-euro";
import { formatWholeEuro } from "@/lib/user-api";

export function DailyLedgerTrend({ data }: { data: ChartsResponse }) {
  const dates = data.range.start <= data.range.end
    ? eachDayOfInterval({ start: parseISO(data.range.start), end: parseISO(data.range.end) }).map((date) => format(date, "yyyy-MM-dd"))
    : [];
  const current = new Map(data.daily.map((row) => [row.date, row]));
  const previous = new Map(data.comparison_daily?.map((row) => [row.date, row]) ?? []);
  const priorRange = data.comparison_coverage;
  const priorDates = priorRange && priorRange.start <= priorRange.end
    ? eachDayOfInterval({ start: parseISO(priorRange.start), end: parseISO(priorRange.end) }).map((date) => format(date, "yyyy-MM-dd"))
    : [];
  const rows = dates.map((date, index) => ({
    date,
    previousDate: priorDates[index],
    current: current.get(date)?.revenue ?? null,
    previous: priorDates[index] ? previous.get(priorDates[index])?.revenue ?? null : null,
  }));
  const [selectedDate, setSelectedDate] = useState(dates[0] ?? "");
  const selected = rows.find((row) => row.date === selectedDate) ?? rows[0];
  const readable = (date: string | undefined, comparative = false) => {
    if (!date) return "上期无对应日期";
    const record = (comparative ? previous : current).get(date);
    return `${date}：${record ? `${record.is_open ?? "已记录"}，${formatWholeEuro(record.revenue)}` : "未录入，—"}`;
  };
  const coverage = data.period_coverage;
  const incomplete = coverage && (coverage.record_days < coverage.interval_days
    || (priorRange && priorRange.record_days < priorRange.interval_days));
  const comparison = data.ledger_comparison;
  const comparisonMessage = comparison?.status === "comparable"
    ? `每日台账营业额较上期 ${comparison.change_percent! > 0 ? "+" : ""}${comparison.change_percent!.toFixed(1)}%`
    : comparison?.status === "zero_previous" ? "上期每日台账营业额为 0，不可比较增幅。"
      : comparison?.status === "no_current_records" ? "本期没有已记录每日台账，不可比较。"
        : comparison?.status === "no_previous_records" ? "上期没有已记录每日台账，不可比较。"
          : "暂无每日台账同期数据，不可比较。";

  return <section aria-label="每日台账营业额趋势" className="grid min-w-0 gap-2">
    <h3 className="font-semibold">营业额趋势</h3>
    <p className="text-sm text-muted-foreground">每日台账营业额（€）；公司结算收入不计入日曲线及同期变化。</p>
    <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="趋势图例">
      <span className="flex items-center gap-2"><span aria-hidden="true" className="h-1 w-6 bg-primary" />本期每日台账</span>
      {priorRange && <span className="flex items-center gap-2"><span aria-hidden="true" className="w-6 border-t-2 border-dashed border-[var(--chart-series-2)]" />上期每日台账</span>}
    </div>
    {coverage && <div className="grid gap-1 text-sm text-muted-foreground">
      <p>本期已记录 {coverage.record_days} / {coverage.interval_days} 天{priorRange ? `；上期已记录 ${priorRange.record_days} / ${priorRange.interval_days} 天` : ""}</p>
      {priorRange && <p>上期有效范围：{priorRange.start} 至 {priorRange.end}</p>}
      {comparison?.short_previous_month && <p>上月较短，比较截止至上月实际末日；没有对应日期的部分不补造数据。</p>}
      {incomplete && <p>记录覆盖不完整，比较仅反映已记录每日台账。</p>}
      <p>{comparisonMessage}</p>
    </div>}
    <div data-testid="chart-panel-plot" className="h-48 min-h-48 w-full min-w-0">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 10, right: 12, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis dataKey="date" tickFormatter={(date: string) => date.slice(8)} minTickGap={26} tick={{ fontSize: 12 }} />
          <YAxis width={52} tick={{ fontSize: 12 }} tickFormatter={formatCompactEuro} />
          <Tooltip content={({ active, payload }) => {
            const row = payload?.[0]?.payload as typeof rows[number] | undefined;
            return active && row ? <div className="max-w-60 rounded-md border bg-white p-3 text-sm shadow-sm"><p>本期 {readable(row.date)}</p><p>上期 {readable(row.previousDate, true)}</p></div> : null;
          }} />
          <Line name="本期每日台账" type="linear" dataKey="current" stroke="var(--primary)" strokeWidth={3} dot={{ r: 2 }} connectNulls={false} />
          {priorRange && <Line name="上期每日台账" type="linear" dataKey="previous" stroke="var(--chart-series-2)" strokeDasharray="5 4" strokeWidth={2} dot={{ r: 2 }} connectNulls={false} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
    <p className="text-xs text-muted-foreground">坐标缩写：k 为千欧元，m 为百万欧元，b 为十亿欧元；读数显示完整整数金额。</p>
    {selected && <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-x-2 gap-y-1 rounded-md bg-muted/40 p-2">
      <label htmlFor="trend-date" className="text-sm font-medium">趋势读数日期</label>
      <select id="trend-date" value={selected.date} onChange={(event) => setSelectedDate(event.target.value)} className="h-11 w-full min-w-0 rounded-md border bg-white px-3 text-base focus-visible:outline-2 focus-visible:outline-primary">
        {dates.map((date) => <option key={date} value={date}>{date}</option>)}
      </select>
      <div role="status" aria-label="趋势读数" className="col-span-2 grid gap-0.5 break-words text-sm tabular-nums"><p>本期 {readable(selected.date)}</p>{priorRange && <p>上期 {readable(selected.previousDate, true)}</p>}</div>
    </div>}
  </section>;
}
