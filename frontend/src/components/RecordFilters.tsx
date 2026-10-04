import { addMonths, format, parseISO } from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { DateRange, RecordRangeMode } from "@/lib/business-record-ranges";
import { customMonthRange, monthRange } from "@/lib/business-record-ranges";

interface RecordFiltersProps {
  mode: RecordRangeMode;
  range: DateRange;
  today: string;
  exporting: boolean;
  exportError: string;
  onChange(mode: RecordRangeMode, range: DateRange): void;
  onExport(): void;
}

export function RecordFilters({ mode, range, today, exporting, exportError, onChange, onExport }: RecordFiltersProps) {
  const currentMonth = today.slice(0, 7);
  const selectedMonth = range.start.slice(0, 7);
  const [dateDraft, setDateDraft] = useState(range);
  const [customOpen, setCustomOpen] = useState(mode === "custom");
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    setDateDraft(range);
    setValidationError("");
  }, [range.start, range.end]);
  useEffect(() => {
    setCustomOpen(mode === "custom");
    setValidationError("");
  }, [mode]);

  const chooseMonth = (nextMonth: string) => {
    if (nextMonth > currentMonth) {
      setValidationError("未来月份不可选择");
      return;
    }
    try {
      const nextRange = monthRange(nextMonth);
      setValidationError("");
      setCustomOpen(false);
      onChange("month", nextRange);
    } catch {
      setValidationError("请选择有效月份");
    }
  };
  const moveMonth = (amount: number) => {
    const next = format(addMonths(parseISO(`${selectedMonth}-01`), amount), "yyyy-MM");
    chooseMonth(next);
  };
  const openCustom = () => {
    const next = { startMonth: selectedMonth, endMonth: selectedMonth };
    setValidationError("");
    setCustomOpen(true);
    const nextRange = customMonthRange(next, today);
    setDateDraft(nextRange);
    onChange("custom", nextRange);
  };
  const updateDate = (patch: Partial<typeof range>) => {
    const next = { ...dateDraft, ...patch };
    setDateDraft(next);
    const error = !next.start || !next.end ? "请选择开始日期和结束日期"
      : next.start > today || next.end > today ? "未来日期不可选择"
        : next.start > next.end ? "结束日期不能早于开始日期" : "";
    setValidationError(error);
    if (!error) {
      onChange("custom", next);
    }
  };
  const returnToMonth = () => {
    setCustomOpen(false);
    setValidationError("");
    onChange("month", monthRange(selectedMonth));
  };

  return (
    <section aria-label="记录筛选" className="grid min-w-0 gap-3 md:grid-cols-[auto_1fr] md:items-end">
      <div className="grid min-w-0 grid-cols-[2.5rem_minmax(0,1fr)_2.5rem] items-end gap-2 md:grid-cols-[2.5rem_9rem_2.5rem]" aria-label="月份导航">
        <Button aria-label="前一月" className="h-10 w-10" onClick={() => moveMonth(-1)} size="icon" type="button" variant="outline">
          <ChevronLeft aria-hidden="true" />
        </Button>
        <label className="grid min-w-0 gap-1 text-sm font-medium">
          月份
          <Input aria-label="月份" className="h-10 min-w-0" max={currentMonth} onChange={(event) => chooseMonth(event.target.value)} type="month" value={selectedMonth} />
        </label>
        <Button aria-label="后一月" className="h-10 w-10" disabled={selectedMonth >= currentMonth} onClick={() => moveMonth(1)} size="icon" type="button" variant="outline">
          <ChevronRight aria-hidden="true" />
        </Button>
      </div>
      {customOpen && (
        <div className="grid min-w-0 grid-cols-2 gap-2 md:col-span-2 md:row-start-2" data-testid="record-filter-dates">
          <label className="grid min-w-0 gap-1 text-sm font-medium">开始日期
            <Input aria-label="开始日期" className="h-11 min-w-0 px-2" max={today} onChange={(event) => updateDate({ start: event.target.value })} type="date" value={dateDraft.start} />
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium">结束日期
            <Input aria-label="结束日期" className="h-11 min-w-0 px-2" max={today} onChange={(event) => updateDate({ end: event.target.value })} type="date" value={dateDraft.end} />
          </label>
        </div>
      )}
      <div className="grid min-w-0 grid-cols-2 gap-2 md:col-start-2 md:row-start-1 md:grid-cols-[auto_auto] md:justify-start">
        <Button aria-pressed={customOpen} className="h-10 min-w-0" onClick={customOpen ? returnToMonth : openCustom} type="button" variant="outline">
          {customOpen ? "单月浏览" : "自定义范围"}
        </Button>
        <Button className="h-10 min-w-0" disabled={exporting || Boolean(validationError)} onClick={onExport} type="button">
          导出当前范围
        </Button>
      </div>
      {validationError && <p role="alert" className="text-sm text-destructive md:col-span-2">{validationError}</p>}
      {exportError && <p role="alert" className="text-sm text-destructive md:col-span-2">{exportError}</p>}
    </section>
  );
}
