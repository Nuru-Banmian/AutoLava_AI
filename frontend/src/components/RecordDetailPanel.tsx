import { format, isValid, parseISO } from "date-fns";
import { Link } from "react-router-dom";

import type { RecordSnapshot } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatWholeEuro } from "@/lib/user-api";

export type RecordDetail = RecordSnapshot | { id: null; date: string };

export interface RecordDetailPanelProps {
  record: RecordDetail;
  canEdit: boolean;
  canDelete: boolean;
  washCountEnabled: boolean;
  onEdit?(date: string): void;
  onDelete(trigger: HTMLButtonElement): void;
  mobile?: boolean;
}

const statusClasses = {
  "营业": "bg-emerald-100 text-emerald-800",
  "休息": "bg-slate-200 text-slate-700",
  "提前休息": "bg-amber-100 text-amber-800",
} as const;

function formatBookkeepingEventTime(value: string) {
  if (!value) return null;
  const parsed = parseISO(value);
  return isValid(parsed) ? format(parsed, "yyyy年M月d日 HH:mm") : null;
}

export function RecordDetailPanel({
  record,
  canEdit,
  canDelete,
  washCountEnabled,
  onEdit,
  onDelete,
  mobile = false,
}: RecordDetailPanelProps) {
  const isUnrecorded = record.id === null;
  const composedItems = !isUnrecorded && record.income_mode === "composed" ? record.items : [];
  const summaryItemClass = "rounded-xl bg-muted/50 p-3";
  const summaryValueClass = "mt-1 text-lg font-semibold";
  const status = isUnrecorded ? "未录入" : record.is_open;
  const showWashCount = !isUnrecorded && washCountEnabled && typeof record.wash_count === "number" && record.wash_count > 0;
  const bookkeepingEvents = isUnrecorded ? [] : [
    {
      action: "创建记录",
      actor: record.created_by_name?.trim() || `用户 ${record.created_by}`,
      at: record.created_at,
      formattedAt: formatBookkeepingEventTime(record.created_at),
    },
    ...(record.updated_at !== record.created_at || record.updated_by !== record.created_by ? [{
      action: "最后修改",
      actor: record.updated_by_name?.trim() || `用户 ${record.updated_by}`,
      at: record.updated_at,
      formattedAt: formatBookkeepingEventTime(record.updated_at),
    }] : []),
  ].filter((event) => event.formattedAt !== null);

  return (
    <Card className={mobile ? "border-0 shadow-none" : "overflow-hidden"}>
      <CardHeader className={`flex-row flex-wrap items-center gap-2 space-y-0 ${mobile ? "p-1 pb-5 pr-14" : "p-5 pb-4"}`}>
        <CardTitle className={mobile ? "text-2xl leading-tight" : "text-xl leading-tight"}>{format(parseISO(record.date), "yyyy年M月d日")}</CardTitle>
        <span className={`rounded-full px-2.5 py-1 text-sm font-medium ${isUnrecorded ? "bg-muted text-muted-foreground" : statusClasses[record.is_open]}`}>
          {status}
        </span>
      </CardHeader>
      <CardContent className={mobile ? "grid gap-5 p-1 pt-0" : "grid gap-5 p-5 pt-0"}>
        <section aria-label="营业摘要" className="grid grid-cols-2 gap-3 text-sm">
          <div className={summaryItemClass}><p className="text-muted-foreground">营业额</p><p className={summaryValueClass}>{isUnrecorded ? "—" : formatWholeEuro(record.daily_revenue)}</p></div>
          <div className={summaryItemClass}><p className="text-muted-foreground">天气</p><p className={summaryValueClass}>{isUnrecorded ? "—" : record.weather ?? "—"}</p></div>
        </section>

        {showWashCount && <p className="text-sm font-medium text-muted-foreground">洗车 {record.wash_count} 辆</p>}

        {!isUnrecorded && record.income_mode === "legacy_total" ? (
          <p className="rounded-lg bg-muted px-3 py-2.5 text-base text-muted-foreground">历史记录仅保存营业额总计</p>
        ) : !isUnrecorded && composedItems.length > 0 ? (
          <section className="grid gap-2" aria-labelledby={`income-details-${record.date}`}>
            <h4 className="font-semibold" id={`income-details-${record.date}`}>收入明细</h4>
            <dl aria-label="收入明细" className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,9rem),1fr))] gap-2 text-base">
              {composedItems.map((item) => (
                <div key={item.id} className="flex min-w-0 items-start justify-between gap-3 rounded-lg bg-muted/50 px-3 py-2.5">
                  <dt className="min-w-0 break-words text-muted-foreground">{item.category_name}</dt>
                  <dd className="shrink-0 font-medium tabular-nums">{formatWholeEuro(item.amount)}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}

        {!isUnrecorded && record.activity && (
          <p className="min-w-0 whitespace-pre-wrap break-words rounded-lg border px-3 py-2.5 text-base [overflow-wrap:anywhere]">
            <span className="text-muted-foreground">事件：</span>
            {record.activity}
          </p>
        )}
        {bookkeepingEvents.length > 0 && (
          <section className="grid gap-2" aria-labelledby={`bookkeeping-events-${record.date}`}>
            <div className="flex items-baseline justify-between gap-3">
              <h4 className="font-semibold" id={`bookkeeping-events-${record.date}`}>记账事件</h4>
              <span className="text-xs text-muted-foreground">自动记录</span>
            </div>
            <ol className="grid gap-2 text-sm">
              {bookkeepingEvents.map((event) => (
                <li key={event.action} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 rounded-lg bg-muted/50 px-3 py-2.5">
                  <span><span className="font-medium">{event.actor}</span>{event.action}</span>
                  <time className="shrink-0 tabular-nums text-muted-foreground" dateTime={event.at}>{event.formattedAt}</time>
                </li>
              ))}
            </ol>
          </section>
        )}
        <div className={`flex flex-wrap gap-2 border-t pt-4 ${mobile ? "" : "items-center"}`}>
          {canEdit && <Button asChild className={mobile ? "h-11 w-full text-base" : "h-10 text-base"}><Link to={`/ledger?date=${record.date}`} onClick={onEdit ? (event) => { event.preventDefault(); onEdit(record.date); } : undefined}>修改这天记录</Link></Button>}
          {canDelete && !isUnrecorded && <Button className={mobile ? "h-11 w-full text-base" : "h-10 text-base"} type="button" variant="destructive" onClick={(event) => onDelete(event.currentTarget)}>删除记录</Button>}
        </div>
      </CardContent>
    </Card>
  );
}
