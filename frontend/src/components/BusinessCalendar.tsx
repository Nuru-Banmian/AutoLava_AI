import { eachDayOfInterval, endOfMonth, format, getDay, parseISO, startOfMonth } from "date-fns";

import type { ChartsResponse } from "@/api/types";
import { formatWholeEuro } from "@/lib/user-api";

export function BusinessCalendar({ data, today, onSelectDate }: {
  data: ChartsResponse;
  today: string;
  onSelectDate?: (date: string) => void;
}) {
  const month = parseISO(data.range.start);
  const dates = eachDayOfInterval({ start: startOfMonth(month), end: endOfMonth(month) }).map((date) => format(date, "yyyy-MM-dd"));
  const offset = (getDay(startOfMonth(month)) + 6) % 7;
  const records = new Map(data.daily.map((row) => [row.date, row]));
  const maximum = Math.max(1, ...data.daily.map((row) => row.revenue));
  const available = dates.filter((date) => date >= data.range.start && date <= data.range.end && date <= today);
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
        const opacity = record && enabled ? 0.08 + (record.revenue / maximum) * 0.32 : 0;
        return <button key={date} type="button" aria-label={label(date)} title={label(date)} disabled={!enabled}
          className="flex min-h-[60px] min-w-0 flex-col items-center justify-start gap-0.5 rounded-md border px-0 py-1.5 text-xs tabular-nums disabled:bg-muted/30 disabled:text-muted-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary lg:aspect-square lg:min-h-11 lg:justify-center"
          style={enabled ? { backgroundColor: `color-mix(in oklab, var(--primary) ${opacity * 100}%, transparent)` } : undefined}
          onClick={() => onSelectDate?.(date)}>
          <span className="font-semibold">{Number(date.slice(8))}</span><span className="break-all leading-tight">{state(date)}</span>
        </button>;
      })}
    </div>
    </div>
    <footer className="border-t pt-2 text-xs text-muted-foreground">颜色深浅表示营业额；休息、提前休息及未录入按日期标明。公司结算不分摊到每日。</footer>
  </section>;
}
