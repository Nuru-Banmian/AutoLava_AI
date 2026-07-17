import { addDays, eachDayOfInterval, endOfMonth, endOfWeek, format, parseISO, startOfMonth, startOfWeek } from "date-fns";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";

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
  const dayIds = days.map((day) => format(day, "yyyy-MM-dd"));
  const initialFocus = dayIds.includes(selected) && selected <= today
    ? selected
    : [...dayIds].reverse().find((iso) => iso <= today) ?? "";
  const [focusedDate, setFocusedDate] = useState(initialFocus);
  const buttonRefs = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => setFocusedDate(initialFocus), [initialFocus]);

  const moveFocus = (from: Date, event: KeyboardEvent<HTMLButtonElement>) => {
    let target: Date | null = null;
    if (event.key === "ArrowLeft") target = addDays(from, -1);
    if (event.key === "ArrowRight") target = addDays(from, 1);
    if (event.key === "ArrowUp") target = addDays(from, -7);
    if (event.key === "ArrowDown") target = addDays(from, 7);
    if (event.key === "Home") target = startOfWeek(from, { weekStartsOn: 1 });
    if (event.key === "End") target = endOfWeek(from, { weekStartsOn: 1 });
    if (!target) return;
    event.preventDefault();
    let iso = format(target, "yyyy-MM-dd");
    if (event.key === "End" && iso > today) iso = today;
    if (iso > today || !dayIds.includes(iso)) return;
    setFocusedDate(iso);
    buttonRefs.current.get(iso)?.focus();
  };
  const weeks = Array.from({ length: days.length / 7 }, (_, index) => days.slice(index * 7, index * 7 + 7));

  return (
    <div aria-label={`${format(monthDate, "yyyy年M月")}日历`} role="grid" className="grid gap-1">
      <div role="row" className="grid grid-cols-7 gap-1">
        {weekdayLabels.map((label) => (
          <div key={label} role="columnheader" aria-label={`星期${label}`} className="pb-1 text-center text-xs text-muted-foreground">
            {label}
          </div>
        ))}
      </div>
      {weeks.map((week) => (
        <div key={format(week[0], "yyyy-MM-dd")} role="row" className="grid grid-cols-7 gap-1">
          {week.map((day) => {
            const iso = format(day, "yyyy-MM-dd");
            const recorded = recordedDates.has(iso);
            const inMonth = iso.startsWith(`${month}-`);
            return (
              <div key={iso} role="gridcell" aria-selected={iso === selected} className="aspect-square min-w-0">
                <button
                  type="button"
                  aria-label={`${format(day, "yyyy年M月d日")}${recorded ? "，已有记录" : ""}`}
                  aria-pressed={iso === selected}
                  tabIndex={iso === focusedDate ? 0 : -1}
                  data-recorded={recorded || undefined}
                  data-empty={inMonth && iso <= today && !recorded || undefined}
                  data-outside={!inMonth || undefined}
                  disabled={iso > today}
                  onClick={() => onSelect(iso)}
                  onFocus={() => setFocusedDate(iso)}
                  onKeyDown={(event) => moveFocus(day, event)}
                  ref={(button) => {
                    if (button) buttonRefs.current.set(iso, button);
                    else buttonRefs.current.delete(iso);
                  }}
                  className={cn(
                    "relative flex size-full min-w-0 items-center justify-center rounded-lg text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-30",
                    inMonth ? "text-foreground" : "text-muted-foreground",
                    iso === selected ? "bg-primary font-semibold text-primary-foreground" : "hover:bg-accent",
                  )}
                >
                  {format(day, "d")}
                  {recorded && <span aria-hidden="true" className={cn("absolute bottom-1 size-1 rounded-full", iso === selected ? "bg-primary-foreground" : "bg-primary")} />}
                  {!recorded && inMonth && iso <= today && <span aria-hidden="true" className={cn("absolute bottom-1 text-[9px]", iso === selected ? "text-primary-foreground" : "text-muted-foreground")}>空</span>}
                </button>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
