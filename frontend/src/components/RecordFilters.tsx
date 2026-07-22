import { addMonths, format, parseISO } from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { DateRange, MonthSelection, MonthSelectionIssue, RecordRangeMode } from "@/lib/business-record-ranges";
import { customMonthRange, monthRange, monthSelectionIssue } from "@/lib/business-record-ranges";

interface RecordFiltersProps {
  mode: RecordRangeMode;
  range: DateRange;
  today: string;
  exporting: boolean;
  exportError: string;
  onChange(mode: RecordRangeMode, range: DateRange): void;
  onExport(): void;
}

const monthSelectionMessages: Record<MonthSelectionIssue, string> = {
  missing: "请选择开始月份和结束月份",
  invalid: "请选择有效月份",
  future: "未来月份不可选择",
  reversed: "结束月份不能早于开始月份",
};

export function RecordFilters({ mode, range, today, exporting, exportError, onChange, onExport }: RecordFiltersProps) {
  const currentMonth = today.slice(0, 7);
  const selectedMonth = range.start.slice(0, 7);
  const [customDraft, setCustomDraft] = useState<MonthSelection>({ startMonth: selectedMonth, endMonth: range.end.slice(0, 7) });
  const [customOpen, setCustomOpen] = useState(mode === "custom");
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    setCustomDraft({ startMonth: range.start.slice(0, 7), endMonth: range.end.slice(0, 7) });
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
    setCustomDraft(next);
    setValidationError("");
    setCustomOpen(true);
    onChange("custom", customMonthRange(next, today));
  };
  const updateCustom = (patch: Partial<MonthSelection>) => {
    const next = { ...customDraft, ...patch };
    const issue = monthSelectionIssue(next, currentMonth);
    setCustomDraft(next);
    setValidationError(issue ? monthSelectionMessages[issue] : "");
    if (!issue) onChange("custom", customMonthRange(next, today));
  };
  const returnToMonth = () => {
    setCustomOpen(false);
    setValidationError("");
    onChange("month", monthRange(selectedMonth));
  };

  return (
    <section aria-label="记录筛选" className="grid min-w-0 gap-3 md:grid-cols-[minmax(17rem,24rem)_auto] md:items-end">
      <div className="grid min-w-0 grid-cols-[2.5rem_minmax(0,1fr)_2.5rem] items-end gap-2" aria-label="月份导航">
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
        <div className="grid min-w-0 grid-cols-2 gap-2 md:col-span-2" data-testid="record-filter-months">
          <label className="grid min-w-0 gap-1 text-sm font-medium">开始月份
            <Input aria-label="开始月份" className="h-10 min-w-0 px-2" max={currentMonth} onChange={(event) => updateCustom({ startMonth: event.target.value })} type="month" value={customDraft.startMonth} />
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium">结束月份
            <Input aria-label="结束月份" className="h-10 min-w-0 px-2" max={currentMonth} onChange={(event) => updateCustom({ endMonth: event.target.value })} type="month" value={customDraft.endMonth} />
          </label>
        </div>
      )}
      <div className="grid min-w-0 grid-cols-2 gap-2 md:col-start-2 md:row-start-1 md:flex">
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
