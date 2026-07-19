import { format, parseISO } from "date-fns";

import type { RecordTableRow } from "@/components/RecordTable";
import { formatWholeEuro } from "@/lib/user-api";

interface MobileRecordListProps {
  records: RecordTableRow[];
  selectedDate: string | null;
  onSelect(record: RecordTableRow, trigger: HTMLButtonElement): void;
}

export function MobileRecordList({ records, selectedDate, onSelect }: MobileRecordListProps) {
  return (
    <div className="divide-y divide-border">
      {records.map((record) => {
        const dateLabel = format(parseISO(record.date), "yyyy年M月d日");
        const isUnrecorded = record.id === null;
        const status = isUnrecorded ? "未录入" : record.is_open;
        const revenue = isUnrecorded ? "—" : formatWholeEuro(record.daily_revenue);
        return (
          <button
            key={record.id ?? record.date}
            type="button"
            aria-pressed={record.date === selectedDate}
            className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 overflow-hidden px-3 py-2 text-left aria-pressed:bg-primary/10"
            aria-label={`${dateLabel}，${status}，${revenue}`}
            onClick={(event) => onSelect(record, event.currentTarget)}
          >
            <span className="truncate">{dateLabel}</span>
            <span className="whitespace-nowrap">{status}</span>
            <span className="whitespace-nowrap text-right">{revenue}</span>
          </button>
        );
      })}
    </div>
  );
}
