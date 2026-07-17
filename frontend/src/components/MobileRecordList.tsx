import { format, parseISO } from "date-fns";

import type { RecordSnapshot } from "@/api/types";
import { formatMoney } from "@/lib/user-api";

interface MobileRecordListProps {
  records: RecordSnapshot[];
  selectedId: number | null;
  onSelect(record: RecordSnapshot, trigger: HTMLButtonElement): void;
}

export function MobileRecordList({ records, selectedId, onSelect }: MobileRecordListProps) {
  return (
    <div className="divide-y divide-border">
      {records.map((record) => {
        const dateLabel = format(parseISO(record.date), "yyyy年M月d日");
        return (
          <button
            key={record.id}
            type="button"
            aria-pressed={record.id === selectedId}
            className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 overflow-hidden px-3 py-3 text-left aria-pressed:bg-primary/10"
            aria-label={`${dateLabel}，${record.is_open}，${formatMoney(record.daily_revenue)}`}
            onClick={(event) => onSelect(record, event.currentTarget)}
          >
            <span className="truncate">{dateLabel}</span>
            <span className="whitespace-nowrap">{record.is_open}</span>
            <span className="whitespace-nowrap text-right">{formatMoney(record.daily_revenue)}</span>
          </button>
        );
      })}
    </div>
  );
}
