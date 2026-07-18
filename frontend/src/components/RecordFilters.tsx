import { useEffect, useState } from "react";

import { NativeDateInput } from "@/components/NativeDateInput";
import type { DateRange, RecordRangeMode } from "@/lib/business-record-ranges";
import { recordRange } from "@/lib/business-record-ranges";

interface RecordFiltersProps {
  mode: RecordRangeMode;
  range: DateRange;
  today: string;
  exporting: boolean;
  exportError: string;
  onChange(mode: RecordRangeMode, range: DateRange): void;
  onExport(): void;
}

const presets: { mode: Exclude<RecordRangeMode, "custom">; label: string }[] = [
  { mode: "current-month", label: "本月" },
  { mode: "previous-month", label: "上月" },
];

export function RecordFilters({ mode, range, today, exporting, exportError, onChange, onExport }: RecordFiltersProps) {
  const [customDraft, setCustomDraft] = useState<DateRange>(range);
  const [customOpen, setCustomOpen] = useState(mode === "custom");

  useEffect(() => {
    setCustomDraft(range);
    setCustomOpen(mode === "custom");
  }, [mode, range]);

  const choosePreset = (next: Exclude<RecordRangeMode, "custom">) => {
    setCustomOpen(false);
    onChange(next, recordRange(next, today));
  };
  const customRangeIsValid = (next: DateRange) => next.start !== "" && next.end !== "" && next.start <= next.end && next.end <= today;
  const updateCustom = (patch: Partial<DateRange>) => {
    const next = { ...customDraft, ...patch };
    setCustomDraft(next);
    if (customRangeIsValid(next)) {
      onChange("custom", next);
    }
  };

  return (
    <section aria-label="记录筛选" className="grid gap-2 md:flex md:flex-wrap md:items-end">
      <div className="grid grid-cols-3 gap-2 md:flex" aria-label="日期范围预设">
        {presets.map((preset) => (
          <button
            key={preset.mode}
            type="button"
            aria-pressed={mode === preset.mode}
            onClick={() => choosePreset(preset.mode)}
            className="h-10 w-full rounded-md border border-border px-3 py-2 text-sm aria-pressed:bg-primary aria-pressed:text-primary-foreground md:w-auto"
          >
            {preset.label}
          </button>
        ))}
        <button
          type="button"
          aria-pressed={mode === "custom"}
          onClick={() => {
            setCustomOpen(true);
            if (customRangeIsValid(customDraft)) onChange("custom", customDraft);
          }}
          className="h-10 w-full rounded-md border border-border px-3 py-2 text-sm aria-pressed:bg-primary aria-pressed:text-primary-foreground md:w-auto"
        >
          自定义
        </button>
      </div>
      {customOpen && (
        <div className="grid grid-cols-2 gap-2" data-testid="record-filter-dates">
          <label className="grid min-w-0 gap-1 text-sm">开始日期
            <NativeDateInput aria-label="开始日期" max={today} value={customDraft.start} onChange={(event) => updateCustom({ start: event.target.value })} />
          </label>
          <label className="grid min-w-0 gap-1 text-sm">结束日期
            <NativeDateInput aria-label="结束日期" max={today} value={customDraft.end} onChange={(event) => updateCustom({ end: event.target.value })} />
          </label>
        </div>
      )}
      <button type="button" disabled={exporting} onClick={onExport} className="h-10 w-full rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60 md:w-auto">
        导出当前范围
      </button>
      {exportError && <p role="alert" className="basis-full text-sm text-destructive">{exportError}</p>}
    </section>
  );
}
