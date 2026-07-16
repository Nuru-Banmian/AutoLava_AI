import { format, parseISO } from "date-fns";
import { Link } from "react-router-dom";

import type { RecordSnapshot } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatMoney } from "@/lib/user-api";

interface RecordDetailProps {
  record: RecordSnapshot;
  canEdit: boolean;
  canManage: boolean;
  onManage(): void;
}

export function RecordDetail({ record, canEdit, canManage, onManage }: RecordDetailProps) {
  const composedItems = record.income_mode === "composed" ? record.items : [];

  return (
    <Card>
      <CardHeader className="p-4 pb-3">
        <CardTitle>{format(parseISO(record.date), "yyyy年M月d日")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 p-4 pt-0">
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div><p className="text-muted-foreground">营业状态</p><p className="font-medium">{record.is_open}</p></div>
          <div><p className="text-muted-foreground">营业额</p><p className="font-medium">{formatMoney(record.daily_revenue)}</p></div>
          <div><p className="text-muted-foreground">洗车数量</p><p className="font-medium">洗车数量 {record.wash_count ?? "—"}</p></div>
          <div><p className="text-muted-foreground">天气</p><p className="font-medium">{record.weather ?? "—"}</p></div>
        </div>

        {record.income_mode === "legacy_total" ? (
          <p className="rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">历史记录仅保存营业额总计</p>
        ) : composedItems.length > 0 ? (
          <div className="grid gap-1 text-sm">
            {composedItems.map((item) => (
              <div key={item.id} className="flex justify-between gap-4"><span>{item.category_name}</span><span>{formatMoney(item.amount)}</span></div>
            ))}
          </div>
        ) : null}

        {record.activity && <p className="text-sm"><span className="text-muted-foreground">活动：</span>{record.activity}</p>}
        <div className="flex flex-wrap gap-2">
          {canEdit && <Button asChild><Link to={`/ledger?date=${record.date}`}>修改这天记录</Link></Button>}
          {canManage && <Button type="button" variant="outline" onClick={onManage}>管理这天记录</Button>}
        </div>
      </CardContent>
    </Card>
  );
}
