import { format, parseISO } from "date-fns";
import type { KeyboardEvent } from "react";

import type { RecordSnapshot } from "@/api/types";
import { formatMoney } from "@/lib/user-api";

export type RecordTableRow = RecordSnapshot | { id: null; date: string };

interface RecordTableProps {
  records: RecordTableRow[];
  selectedDate: string | null;
  loading: boolean;
  error: Error | null;
  onSelect(record: RecordTableRow): void;
  onRetry(): void;
}

export function RecordTable({ records, selectedDate, loading, error, onSelect, onRetry }: RecordTableProps) {
  function activateFromKeyboard(event: KeyboardEvent<HTMLTableRowElement>, record: RecordTableRow) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onSelect(record);
  }

  if (loading) return <div role="status" className="animate-pulse rounded-md bg-muted p-4">正在加载记录…</div>;
  if (error) return <div role="alert" className="grid gap-2 rounded-md border border-destructive p-4">{error.message}<button type="button" onClick={onRetry} className="w-fit rounded-md border border-border px-3 py-2">重试</button></div>;
  if (records.length === 0) return <p className="rounded-md border border-dashed p-4 text-muted-foreground">暂无记录</p>;

  return (
    <div className="w-full">
      <table className="w-full table-fixed text-left text-sm">
        <thead className="border-b border-border text-muted-foreground">
          <tr><th scope="col" className="px-3 py-2">日期</th><th scope="col" className="px-3 py-2">状态</th><th scope="col" className="px-3 py-2">总营业额</th><th scope="col" className="px-3 py-2">天气</th></tr>
        </thead>
        <tbody>
          {records.map((record) => {
            const dateLabel = format(parseISO(record.date), "yyyy年M月d日");
            const isUnrecorded = record.id === null;
            const selected = record.date === selectedDate;
            return (
              <tr
                key={record.id ?? record.date}
                aria-selected={selected}
                tabIndex={0}
                onClick={() => onSelect(record)}
                onKeyDown={(event) => activateFromKeyboard(event, record)}
                className={selected ? "cursor-pointer border-l-4 border-primary bg-primary/10" : "cursor-pointer border-l-4 border-transparent hover:bg-muted/60"}
              >
                <td className="px-3 py-3">{dateLabel}</td>
                <td className="px-3 py-3">{isUnrecorded ? "未录入" : record.is_open}</td>
                <td className="px-3 py-3">{isUnrecorded ? "—" : formatMoney(record.daily_revenue)}</td>
                <td className="px-3 py-3">{isUnrecorded ? "—" : record.weather ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
