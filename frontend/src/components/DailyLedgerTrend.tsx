import { eachDayOfInterval, format, parseISO } from "date-fns";
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
  const readable = (date: string | undefined, comparative = false) => {
    if (!date) return "上期无对应日期";
    const record = (comparative ? previous : current).get(date);
    return `${date}：${record ? `${record.is_open ?? "已记录"}，${formatWholeEuro(record.revenue)}` : "未录入，—"}`;
  };
  const coverage = data.period_coverage;
  const comparison = data.ledger_comparison;
  const comparisonMessage = comparison?.status === "comparable"
    ? `每日台账营业额较上期 ${comparison.change_percent! > 0 ? "+" : ""}${comparison.change_percent!.toFixed(1)}%`
    : comparison?.status === "zero_previous" ? "上期每日台账营业额为 0，不可比较增幅。"
      : comparison?.status === "no_current_records" ? "本期没有已统计每日台账，不可比较。"
        : comparison?.status === "no_previous_records" ? "上期没有已统计每日台账，不可比较。"
          : "暂无每日台账同期数据，不可比较。";

  return <section aria-label="每日台账营业额趋势" className="grid min-w-0 gap-2">
    <h3 className="font-semibold">营业额趋势</h3>
    <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="趋势图例">
      <span className="flex items-center gap-2"><span aria-hidden="true" className="h-1 w-6 bg-primary" />本期每日台账</span>
      {priorRange && <span className="flex items-center gap-2"><span aria-hidden="true" className="w-6 border-t-2 border-dashed border-[var(--chart-series-2)]" />上期每日台账</span>}
    </div>
    {coverage && <p className="text-sm text-muted-foreground">{comparisonMessage}</p>}
    <div data-testid="chart-panel-plot" className="h-48 min-h-48 w-full min-w-0">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 10, right: 12, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis dataKey="date" tickFormatter={(date: string) => date.slice(8)} minTickGap={26} tick={{ fontSize: 12 }} />
          <YAxis width={52} tick={{ fontSize: 12 }} tickFormatter={formatCompactEuro} />
          <Tooltip filterNull={false} content={({ active, payload }) => {
            const row = payload?.[0]?.payload as typeof rows[number] | undefined;
            return active && row ? <div className="max-w-60 rounded-md border bg-white p-3 text-sm shadow-sm"><p>本期 {readable(row.date)}</p><p>上期 {readable(row.previousDate, true)}</p></div> : null;
          }} />
          <Line name="本期每日台账" type="linear" dataKey="current" stroke="var(--primary)" strokeWidth={3} dot={{ r: 2 }} connectNulls={false} />
          {priorRange && <Line name="上期每日台账" type="linear" dataKey="previous" stroke="var(--chart-series-2)" strokeDasharray="5 4" strokeWidth={2} dot={{ r: 2 }} connectNulls={false} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  </section>;
}
