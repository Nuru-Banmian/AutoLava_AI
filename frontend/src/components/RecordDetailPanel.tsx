import { format, parseISO } from "date-fns";
import { Link } from "react-router-dom";

import type { RecordSnapshot } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatWholeEuro } from "@/lib/user-api";

export type RecordDetail = RecordSnapshot | { id: null; date: string };

export interface RecordDetailPanelProps {
  record: RecordDetail;
  canEdit: boolean;
  canManage: boolean;
  onManage(): void;
  mobile?: boolean;
}

export function RecordDetailPanel({ record, canEdit, canManage, onManage, mobile = false }: RecordDetailPanelProps) {
  const isUnrecorded = record.id === null;
  const composedItems = !isUnrecorded && record.income_mode === "composed" ? record.items : [];
  const summaryItemClass = "rounded-xl bg-muted/50 p-3";
  const summaryValueClass = "mt-1 text-lg font-semibold";

  return (
    <Card className={mobile ? "border-0 shadow-none" : "overflow-hidden"}>
      <CardHeader className={mobile ? "p-1 pb-5 pr-14" : "p-5 pb-4"}>
        <CardTitle className={mobile ? "text-2xl leading-tight" : "text-xl leading-tight"}>{format(parseISO(record.date), "yyyy年M月d日")}</CardTitle>
      </CardHeader>
      <CardContent className={mobile ? "grid gap-5 p-1 pt-0" : "grid gap-5 p-5 pt-0"}>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className={summaryItemClass}>
            <p className="text-muted-foreground">营业状态</p>
            <p className={summaryValueClass}>{isUnrecorded ? "未录入" : record.is_open}</p>
          </div>
          <div className={summaryItemClass}><p className="text-muted-foreground">营业额</p><p className={summaryValueClass}>{isUnrecorded ? "—" : formatWholeEuro(record.daily_revenue)}</p></div>
          <div className={summaryItemClass}><p className="text-muted-foreground">洗车数量</p><p className={summaryValueClass}>{isUnrecorded ? "—" : mobile ? record.wash_count ?? "—" : `洗车数量 ${record.wash_count ?? "—"}`}</p></div>
          <div className={summaryItemClass}><p className="text-muted-foreground">天气</p><p className={summaryValueClass}>{isUnrecorded ? "—" : record.weather ?? "—"}</p></div>
        </div>

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

        {!isUnrecorded && record.activity && <p className="rounded-lg border px-3 py-2.5 text-base"><span className="text-muted-foreground">活动：</span>{record.activity}</p>}
        <div className={`flex flex-wrap gap-2 border-t pt-4 ${mobile ? "" : "items-center"}`}>
          {canEdit && <Button asChild className={mobile ? "h-11 w-full text-base" : "h-10 text-base"}><Link to={`/ledger?date=${record.date}`}>修改这天记录</Link></Button>}
          {canManage && !isUnrecorded && <Button className={mobile ? "h-11 w-full text-base" : "h-10 text-base"} type="button" variant="outline" onClick={onManage}>管理这天记录</Button>}
        </div>
      </CardContent>
    </Card>
  );
}
