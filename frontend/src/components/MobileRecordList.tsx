import type { RecordTableRow } from "@/components/RecordTable";
import { formatBusinessRecordDate } from "@/lib/business-record-date";
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
        const dateLabel = formatBusinessRecordDate(record.date);
        const isUnrecorded = record.id === null;
        const status = isUnrecorded ? "未录入" : record.is_open;
        const revenue = isUnrecorded ? "—" : formatWholeEuro(record.daily_revenue);
        return (
          <button
            key={record.date}
            type="button"
            aria-pressed={record.date === selectedDate}
            data-record-date={record.date}
            className="grid min-h-11 w-full grid-cols-[minmax(0,1fr)_4rem_minmax(4rem,max-content)] items-center gap-2 px-2 py-2 text-left text-sm aria-pressed:bg-primary/10"
            aria-label={`${dateLabel}，${status}，${revenue}`}
            onClick={(event) => onSelect(record, event.currentTarget)}
          >
            <span className="flex flex-wrap items-baseline gap-x-1"><span className="whitespace-nowrap">{format(parseISO(record.date), "M月d日")}</span><span className="whitespace-nowrap text-xs text-muted-foreground">{dateLabel.slice(-3).replace("星期", "周")}</span></span>
            <span className="whitespace-nowrap">{status}</span>
            <span className="whitespace-nowrap text-right tabular-nums">{revenue}</span>
          </button>
        );
      })}
    </div>
  );
}
import { format, parseISO } from "date-fns";
