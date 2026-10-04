import { eachDayOfInterval, endOfMonth, format, getDay, parseISO, startOfMonth } from "date-fns";

import type { ChartsResponse } from "@/api/types";
import { formatWholeEuro } from "@/lib/user-api";

const revenueColors = [
  "border-blue-200 bg-blue-100 text-blue-950",
  "border-blue-200 bg-[#cde2fe] text-blue-950",
  "border-blue-300 bg-blue-200 text-blue-950",
  "border-blue-300 bg-[#a9cefd] text-blue-950",
  "border-blue-400 bg-blue-300 text-blue-950",
];

export function BusinessCalendar({ data, today, onSelectDate }: {
  data: ChartsResponse;
  today: string;
  onSelectDate?: (date: string) => void;
}) {
  const month = parseISO(data.range.start);
  const dates = eachDayOfInterval({ start: startOfMonth(month), end: endOfMonth(month) }).map((date) => format(date, "yyyy-MM-dd"));
  const offset = (getDay(startOfMonth(month)) + 6) % 7;
  const records = new Map(data.daily.map((row) => [row.date, row]));
  const available = dates.filter((date) => date >= data.range.start && date <= data.range.end && date <= today);
  const revenues = data.daily.filter((row) => available.includes(row.date) && row.is_open !== "休息").map((row) => row.revenue).sort((a, b) => a - b);
  // Quantiles keep an unusually high day from making every other day look alike.
  const limits = revenues.length ? [...new Set(Array.from({ length: 5 }, (_, index) => revenues[Math.ceil(revenues.length * (index + 1) / 5) - 1]))] : [];
  const colorForBand = (index: number) => revenueColors[limits.length === 1 ? 2 : Math.round(index * 4 / (limits.length - 1))];
  const state = (date: string) => date > today ? "未来"
    : date < data.range.start || date > data.range.end ? "范围外"
      : records.get(date)?.is_open ?? (records.has(date) ? "已记录" : "未录入");
  const label = (date: string) => `${date} ${state(date)}${available.includes(date) ? ` ${records.has(date) ? formatWholeEuro(records.get(date)!.revenue) : "—"}` : ""}`;

  return <section role="region" aria-label="营业日历" className="flex w-full min-w-0 flex-col gap-3 rounded-lg border bg-white p-2.5 sm:p-3 lg:row-span-3 lg:grid lg:grid-rows-subgrid">
    <header className="grid gap-0.5">
    <h3 className="font-semibold">营业日历</h3>
    <p className="text-xs text-muted-foreground">{format(month, "yyyy-MM")} · 每日台账营业额</p>
    </header>
    <div className="grid w-full max-w-[420px] content-start gap-2">
    <div className="grid grid-cols-7 gap-1 text-center text-sm" aria-hidden="true">{["一", "二", "三", "四", "五", "六", "日"].map((day) => <span key={day}>周{day}</span>)}</div>
    <div className="grid grid-cols-7 gap-1" aria-label="按周排列的每日台账">
      {Array.from({ length: offset }, (_, index) => <span key={`blank-${index}`} aria-hidden="true" />)}
      {dates.map((date) => {
        const record = records.get(date);
        const enabled = available.includes(date);
        const resting = record?.is_open === "休息";
        const earlyClose = enabled && record?.is_open === "提前休息";
        const band = record ? limits.findIndex((limit) => record.revenue <= limit) : -1;
        const colors = !enabled ? "border-slate-100 bg-slate-50 text-slate-400"
          : !record ? "border-dashed border-amber-400 bg-amber-50 text-amber-950"
            : resting ? "border-slate-300 bg-slate-200 text-slate-700" : colorForBand(band);
        return <button key={date} type="button" aria-label={label(date)} title={label(date)} disabled={!enabled}
          aria-current={date === today ? "date" : undefined}
          className={`relative flex min-h-[76px] min-w-0 flex-col items-center justify-start gap-0.5 overflow-hidden rounded-md border px-0.5 py-1.5 text-xs tabular-nums ${colors} ${enabled ? "hover:brightness-95" : ""} ${date === today ? "ring-2 ring-slate-900 ring-offset-1" : ""} focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary lg:justify-center`}
          onClick={() => onSelectDate?.(date)}>
          {earlyClose && <span aria-hidden="true" className="absolute right-0 top-0 size-2.5 rounded-bl-sm bg-orange-400 ring-1 ring-orange-900" />}
          <span className="font-semibold">{Number(date.slice(8))}</span>
          {enabled && record && <span className="w-full break-all text-center font-semibold leading-tight">{formatWholeEuro(record.revenue)}</span>}
          <span className="break-all text-[10px] leading-tight">{state(date)}</span>
        </button>;
      })}
    </div>
    </div>
    <footer className="grid gap-2 border-t pt-2 text-xs text-muted-foreground">
      {limits.length > 0 && <div aria-label="营业额颜色图例" className="flex flex-wrap gap-x-3 gap-y-1.5">
        {limits.map((limit, index) => <span key={limit} className="inline-flex items-center gap-1">
          <span aria-hidden="true" className={`size-3 shrink-0 rounded-sm border ${colorForBand(index)}`} />
          {index === 0 ? `${formatWholeEuro(0)}–${formatWholeEuro(limit)}` : `${formatWholeEuro(limits[index - 1] + 1)}–${formatWholeEuro(limit)}`}
        </span>)}
      </div>}
      <div aria-label="营业状态图例" className="flex flex-wrap gap-x-3 gap-y-1.5">
        <span className="inline-flex items-center gap-1"><span aria-hidden="true" className="size-3 rounded-sm border border-slate-300 bg-slate-200" />休息</span>
        <span className="inline-flex items-center gap-1"><span aria-hidden="true" className="size-3 rounded-sm border border-dashed border-amber-400 bg-amber-50" />未录入</span>
        <span className="inline-flex items-center gap-1"><span aria-hidden="true" className="size-2.5 rounded-bl-sm bg-orange-400 ring-1 ring-orange-900" />提前休息角标</span>
      </div>
      <p>蓝色越深，营业额越高；按当前区间已记录的经营日分档。今天用深色描边。公司结算不分摊到每日。</p>
    </footer>
  </section>;
}
