import { addMonths, format, parseISO, subDays } from "date-fns";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef, useEffect, useState } from "react";

import { MonthCalendar } from "@/components/MonthCalendar";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

export interface LedgerDatePickerProps {
  value: string;
  today: string;
  recordedDates: ReadonlySet<string>;
  onChange(date: string): void;
}

function useDesktopPicker() {
  const query = "(min-width: 640px)";
  const [matches, setMatches] = useState(() => typeof window === "undefined" || !window.matchMedia || window.matchMedia(query).matches);

  useEffect(() => {
    if (!window.matchMedia) return;
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return matches;
}

const DateTrigger = forwardRef<HTMLButtonElement, ComponentPropsWithoutRef<"button"> & { value: string }>(function DateTrigger({ value, ...props }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      {...props}
      aria-label={`选择台账日期：${format(parseISO(value), "yyyy年M月d日")}`}
      className="inline-flex min-h-11 items-center gap-2 rounded-xl border bg-card px-3 py-2 text-sm font-medium shadow-sm transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
    >
      <CalendarDays aria-hidden="true" className="size-4 text-primary" />
      {format(parseISO(value), "yyyy年M月d日")}
    </button>
  );
});

function PickerPanel({ value, today, recordedDates, month, setMonth, select }: LedgerDatePickerProps & { month: string; setMonth(month: string): void; select(date: string): void }) {
  const moveMonth = (amount: number) => setMonth(format(addMonths(parseISO(`${month}-01`), amount), "yyyy-MM"));
  const yesterday = format(subDays(parseISO(today), 1), "yyyy-MM-dd");

  return (
    <div className="grid min-w-0 gap-4 pt-1">
      <div className="flex items-center justify-between gap-2 pr-8">
        <button type="button" aria-label="上个月" onClick={() => moveMonth(-1)} className="rounded-lg p-2 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring">
          <ChevronLeft aria-hidden="true" className="size-5" />
        </button>
        <p className="font-semibold">{format(parseISO(`${month}-01`), "yyyy年M月")}</p>
        <button type="button" aria-label="下个月" disabled={month >= today.slice(0, 7)} onClick={() => moveMonth(1)} className="rounded-lg p-2 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-30">
          <ChevronRight aria-hidden="true" className="size-5" />
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button type="button" onClick={() => select(today)} className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover">今天</button>
        <button type="button" onClick={() => select(yesterday)} className="rounded-lg bg-secondary px-3 py-2 text-sm font-medium text-secondary-foreground hover:bg-accent">昨天</button>
      </div>
      <MonthCalendar month={month} selected={value} today={today} recordedDates={recordedDates} onSelect={select} />
      <p className="rounded-lg bg-accent px-3 py-2 text-center text-sm font-medium text-accent-foreground">
        {recordedDates.has(value) ? "编辑已有记录" : "补记历史记录"}
      </p>
    </div>
  );
}

export function LedgerDatePicker({ value, today, recordedDates, onChange }: LedgerDatePickerProps) {
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(value.slice(0, 7));
  const desktop = useDesktopPicker();

  useEffect(() => setMonth(value.slice(0, 7)), [value]);
  const select = (date: string) => {
    onChange(date);
    setOpen(false);
  };
  const panel = <PickerPanel value={value} today={today} recordedDates={recordedDates} onChange={onChange} month={month} setMonth={setMonth} select={select} />;

  if (desktop) {
    return (
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild><DateTrigger value={value} /></DialogTrigger>
        <DialogContent className="left-auto right-6 top-24 w-[min(22rem,calc(100vw-2rem))] translate-x-0 translate-y-0 p-4">
          <DialogTitle className="sr-only">选择台账日期</DialogTitle>
          {panel}
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild><DateTrigger value={value} /></SheetTrigger>
      <SheetContent side="bottom" className="max-h-[90vh] overflow-y-auto rounded-t-2xl p-4 pb-6">
        <SheetTitle className="sr-only">选择台账日期</SheetTitle>
        <div className="mx-auto w-full max-w-sm">{panel}</div>
      </SheetContent>
    </Sheet>
  );
}
