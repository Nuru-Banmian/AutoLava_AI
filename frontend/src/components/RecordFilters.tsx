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

  useEffect(() => setCustomDraft(range), [range]);

  const choosePreset = (next: Exclude<RecordRangeMode, "custom">) => onChange(next, recordRange(next, today));
  const customRangeIsValid = (next: DateRange) => next.start !== "" && next.end !== "" && next.start <= next.end && next.end <= today;
  const updateCustom = (patch: Partial<DateRange>) => {
    const next = { ...customDraft, ...patch };
    setCustomDraft(next);
    if (customRangeIsValid(next)) {
      onChange("custom", next);
    }
  };

  return (
    <section aria-label="记录筛选" className="flex flex-wrap items-end gap-2">
      <div className="flex gap-2" aria-label="日期范围预设">
        {presets.map((preset) => (
          <button
            key={preset.mode}
            type="button"
            aria-pressed={mode === preset.mode}
            onClick={() => choosePreset(preset.mode)}
            className="rounded-md border border-border px-3 py-2 text-sm aria-pressed:bg-primary aria-pressed:text-primary-foreground"
          >
            {preset.label}
          </button>
        ))}
        <button
          type="button"
          aria-pressed={mode === "custom"}
          onClick={() => {
            if (customRangeIsValid(customDraft)) onChange("custom", customDraft);
          }}
          className="rounded-md border border-border px-3 py-2 text-sm aria-pressed:bg-primary aria-pressed:text-primary-foreground"
        >
          自定义
        </button>
      </div>
      <label className="grid gap-1 text-sm">开始日期
        <NativeDateInput aria-label="开始日期" max={today} value={customDraft.start} onChange={(event) => updateCustom({ start: event.target.value })} />
      </label>
      <label className="grid gap-1 text-sm">结束日期
        <NativeDateInput aria-label="结束日期" max={today} value={customDraft.end} onChange={(event) => updateCustom({ end: event.target.value })} />
      </label>
      <button type="button" disabled={exporting} onClick={onExport} className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60">
        导出当前范围
      </button>
      {exportError && <p role="alert" className="basis-full text-sm text-destructive">{exportError}</p>}
    </section>
  );
}
