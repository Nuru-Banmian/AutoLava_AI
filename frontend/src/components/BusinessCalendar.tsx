import { eachDayOfInterval, endOfMonth, format, getDay, parseISO, startOfMonth } from "date-fns";
import { useState } from "react";

import type { ChartsResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { formatCompactEuro } from "@/lib/compact-euro";
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
  const [selectedDate, setSelectedDate] = useState(available[0] ?? "");
  const selected = available.includes(selectedDate) ? selectedDate : available[0];
  const state = (date: string) => date > today ? "未来"
    : date < data.range.start || date > data.range.end ? "范围外"
      : records.get(date)?.is_open ?? (records.has(date) ? "已记录" : "未录入");
  const label = (date: string) => `${date} ${state(date)}${available.includes(date) ? ` ${records.has(date) ? formatWholeEuro(records.get(date)!.revenue) : "—"}` : ""}`;

  return <section role="region" aria-label="营业日历" className="grid min-w-0 gap-3">
    <h3 className="font-semibold">营业日历</h3>
    <p className="break-words text-sm text-muted-foreground">{format(month, "yyyy-MM")} · 所选范围 {data.range.start} 至 {data.range.end}</p>
    <div className="grid grid-cols-7 gap-1 text-center text-sm" aria-hidden="true">{["一", "二", "三", "四", "五", "六", "日"].map((day) => <span key={day}>周{day}</span>)}</div>
    <div className="grid grid-cols-7 gap-1" aria-label="按周排列的每日台账">
      {Array.from({ length: offset }, (_, index) => <span key={`blank-${index}`} aria-hidden="true" />)}
      {dates.map((date) => {
        const record = records.get(date);
        const enabled = available.includes(date);
        const opacity = record && enabled ? 0.04 + (record.revenue / maximum) * 0.16 : 0;
        return <button key={date} type="button" aria-label={label(date)} title={label(date)} disabled={!enabled}
          className="flex min-h-[76px] min-w-0 flex-col items-center justify-start gap-1 rounded-md border px-0 py-2 text-xs tabular-nums disabled:bg-muted/30 disabled:text-muted-foreground focus-visible:outline-2 focus-visible:outline-primary"
          style={enabled ? { backgroundColor: `rgba(30, 58, 95, ${opacity})` } : undefined}
          onFocus={() => setSelectedDate(date)} onPointerEnter={() => enabled && setSelectedDate(date)} onClick={() => { setSelectedDate(date); onSelectDate?.(date); }}>
          <span className="font-semibold">{Number(date.slice(8))}</span><span className="break-all leading-tight">{state(date)}</span>
          {enabled && <span className="text-[11px] leading-tight">{record ? formatCompactEuro(record.revenue) : "—"}</span>}
        </button>;
      })}
    </div>
    {selected && <div className="grid gap-2 rounded-md bg-muted/40 p-3">
      <label htmlFor="calendar-date" className="text-sm font-medium">日历读数日期</label>
      <select id="calendar-date" value={selected} onChange={(event) => setSelectedDate(event.target.value)} className="h-11 w-full min-w-0 rounded-md border bg-white px-3 text-base focus-visible:outline-2 focus-visible:outline-primary">
        {available.map((date) => <option key={date} value={date}>{date}</option>)}
      </select>
      <p role="status" aria-label="日历读数" className="break-words text-sm tabular-nums">{label(selected)}</p>
      {onSelectDate && <Button type="button" variant="outline" className="h-11" onClick={() => onSelectDate(selected)}>查看 {selected} 每日台账</Button>}
    </div>}
    <p className="text-sm text-muted-foreground">颜色深浅仅辅助表示金额；休息和已记录零营业额为真实 €0，未录入为 —。k 表示千欧元，m 表示百万欧元，b 表示十亿欧元，完整金额见读数。公司结算不分摊到日期。</p>
  </section>;
}
