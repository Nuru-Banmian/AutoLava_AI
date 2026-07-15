import { eachDayOfInterval, endOfMonth, endOfWeek, format, parseISO, startOfMonth, startOfWeek } from "date-fns";

import { cn } from "@/lib/utils";

export interface MonthCalendarProps {
  month: string;
  selected: string;
  today: string;
  recordedDates: ReadonlySet<string>;
  onSelect(date: string): void;
}

const weekdayLabels = ["一", "二", "三", "四", "五", "六", "日"];

export function MonthCalendar({ month, selected, today, recordedDates, onSelect }: MonthCalendarProps) {
  const monthDate = parseISO(`${month}-01`);
  const days = eachDayOfInterval({
    start: startOfWeek(startOfMonth(monthDate), { weekStartsOn: 1 }),
    end: endOfWeek(endOfMonth(monthDate), { weekStartsOn: 1 }),
  });

  return (
    <div aria-label={`${format(monthDate, "yyyy年M月")}日历`} role="grid" className="grid grid-cols-7 gap-1">
      {weekdayLabels.map((label) => (
        <div key={label} role="columnheader" aria-label={`星期${label}`} className="pb-1 text-center text-xs text-muted-foreground">
          {label}
        </div>
      ))}
      {days.map((day) => {
        const iso = format(day, "yyyy-MM-dd");
        const recorded = recordedDates.has(iso);
        const inMonth = iso.startsWith(`${month}-`);
        return <div key={iso} role="gridcell" className="aspect-square min-w-0">
          <button
            type="button"
            aria-label={`${format(day, "yyyy年M月d日")}${recorded ? "，已有记录" : ""}`}
            aria-pressed={iso === selected}
            data-recorded={recorded || undefined}
            data-outside={!inMonth || undefined}
            disabled={iso > today}
            onClick={() => onSelect(iso)}
            className={cn(
              "relative flex size-full min-w-0 items-center justify-center rounded-lg text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-30",
              inMonth ? "text-foreground" : "text-muted-foreground",
              iso === selected ? "bg-primary font-semibold text-primary-foreground" : "hover:bg-accent",
            )}
          >
            {format(day, "d")}
            {recorded && <span aria-hidden="true" className={cn("absolute bottom-1 size-1 rounded-full", iso === selected ? "bg-primary-foreground" : "bg-primary")} />}
          </button>
        </div>;
      })}
    </div>
  );
}
