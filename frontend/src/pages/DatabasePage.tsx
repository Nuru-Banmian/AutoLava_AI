import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addMonths, endOfMonth, format, parseISO } from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "@/api/client";
import type { AuditEntry, DatabaseResponse, RecordSnapshot } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { MonthCalendar } from "@/components/MonthCalendar";
import { RecordDetail } from "@/components/RecordDetail";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { amountToCents, centsToMoney, databaseKey, formatMoney, invalidateUserData, storeLocalToday } from "@/lib/user-api";
import { useStore } from "@/stores/StoreProvider";

function monthBounds(month: string) {
  const start = `${month}-01`;
  return { start, end: format(endOfMonth(parseISO(start)), "yyyy-MM-dd") };
}

function averageOpenRevenue(records: RecordSnapshot[]) {
  const open = records.filter((record) => record.is_open === "营业");
  if (!open.length) return centsToMoney(0n);
  const total = open.reduce((sum, record) => sum + (amountToCents(record.daily_revenue) ?? 0n), 0n);
  const count = BigInt(open.length);
  return centsToMoney((total + count / 2n) / count);
}

interface AuditPageResponse {
  items: AuditEntry[];
  total: number;
  page: number;
  page_size: number;
}

interface AuditTarget {
  date: string;
  recordId: number | null;
}

export function DatabasePage() {
  const { selected } = useStore();
  const { user } = useAuth();
  const client = useQueryClient();
  const today = selected ? storeLocalToday(selected) : "";
  const isAdmin = user?.role === "admin";
  const selectedIdRef = useRef(selected?.id);
  selectedIdRef.current = selected?.id;

  const [month, setMonth] = useState(today.slice(0, 7));
  const [selectedDate, setSelectedDate] = useState(today);
  const [adminOpen, setAdminOpen] = useState(false);
  const [auditTarget, setAuditTarget] = useState<AuditTarget | null>(null);
  const [deleting, setDeleting] = useState<RecordSnapshot | null>(null);
  const [rolling, setRolling] = useState<AuditEntry | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setMonth(today.slice(0, 7));
    setSelectedDate(today);
    setAdminOpen(false);
    setAuditTarget(null);
    setDeleting(null);
    setRolling(null);
    setMessage("");
  }, [selected?.id, today]);

  const { start, end } = monthBounds(month || "1970-01");
  const queryString = new URLSearchParams({ start, end, page: "1", page_size: "31" }).toString();
  const records = useQuery({
    queryKey: selected ? databaseKey(selected.id, `${start}:${end}`) : ["database", "none"],
    enabled: Boolean(selected && month),
    queryFn: () => api<DatabaseResponse>(`/database/${selected!.id}/records?${queryString}`),
  });
  const recordedDates = useMemo(() => new Set(records.data?.items.map((record) => record.date) ?? []), [records.data?.items]);
  const selectedRecord = records.data?.items.find((record) => record.date === selectedDate) ?? null;
  const history = useQuery({
    queryKey: ["database", "history", selected?.id, auditTarget?.recordId, auditTarget?.date],
    enabled: Boolean(selected && auditTarget) && isAdmin && adminOpen,
    queryFn: () => api<AuditPageResponse>(`/database/${selected!.id}/history${auditTarget!.recordId === null ? "?page_size=100" : `?record_id=${auditTarget!.recordId}`}`),
  });

  const selectedHistory = history.data?.items.filter((entry) => entry.record_date === auditTarget?.date) ?? [];

  const finish = async (storeId: number) => {
    if (selectedIdRef.current === storeId) {
      setMessage("操作成功");
      setDeleting(null);
      setRolling(null);
    }
    await invalidateUserData(client, storeId);
    await client.invalidateQueries({ queryKey: ["database", "history", storeId] });
  };
  const remove = useMutation({
    mutationFn: ({ storeId, date }: { storeId: number; date: string }) => api<void>(`/ledger/${storeId}/${date}`, { method: "DELETE" }),
    onSuccess: (_data, variables) => finish(variables.storeId),
    onError: (error, variables) => { if (selectedIdRef.current === variables.storeId) setMessage(error instanceof ApiError ? error.detail : "删除失败"); },
  });
  const rollback = useMutation({
    mutationFn: ({ storeId, auditId }: { storeId: number; auditId: number }) => api(`/database/${storeId}/history/${auditId}/rollback`, { method: "POST" }),
    onSuccess: (_data, variables) => finish(variables.storeId),
    onError: (error, variables) => { if (selectedIdRef.current === variables.storeId) setMessage(error instanceof ApiError ? error.detail : "回滚失败"); },
  });

  if (!selected) return <section><h1 className="text-2xl font-semibold">历史记录</h1><p role="status">请先选择门店。</p></section>;
  if (!month || !selectedDate) return <section><h1 className="text-2xl font-semibold">历史记录</h1><p role="status">加载记录…</p></section>;

  const moveMonth = (amount: number) => {
    const next = format(addMonths(parseISO(`${month}-01`), amount), "yyyy-MM");
    setMonth(next);
    setSelectedDate(next === today.slice(0, 7) ? today : `${next}-01`);
    setAdminOpen(false);
    setAuditTarget(null);
  };
  const selectDate = (date: string) => {
    setSelectedDate(date);
    if (date.slice(0, 7) !== month) setMonth(date.slice(0, 7));
    setAdminOpen(false);
    setAuditTarget(null);
  };

  return (
    <section className="mx-auto grid w-full max-w-4xl gap-4">
      <div className="flex items-center justify-between gap-3">
        <div><h1 className="text-2xl font-semibold">历史记录</h1><p className="text-sm text-muted-foreground">按日期查看门店记录</p></div>
        <a className="text-sm text-primary underline-offset-4 hover:underline" href={`/api/database/${selected.id}/export.xlsx?${queryString}`} download>导出本月</a>
      </div>

      <div className="grid grid-cols-3 gap-2" aria-label="本月摘要">
        <Card className="shadow-sm"><CardContent className="p-3"><p className="text-xs text-muted-foreground">本月营业额</p><p className="mt-1 text-sm font-semibold sm:text-lg">{formatMoney(records.data?.sum_daily_revenue ?? "0")}</p></CardContent></Card>
        <Card className="shadow-sm"><CardContent className="p-3"><p className="text-xs text-muted-foreground">记录天数</p><p className="mt-1 text-sm font-semibold sm:text-lg">已记录 {records.data?.items.length ?? 0} 天</p></CardContent></Card>
        <Card className="shadow-sm"><CardContent className="p-3"><p className="text-xs text-muted-foreground">营业日均</p><p className="mt-1 text-sm font-semibold sm:text-lg">营业日均 {averageOpenRevenue(records.data?.items ?? [])}</p></CardContent></Card>
      </div>

      <Card className="shadow-sm">
        <CardContent className="grid gap-3 p-3 sm:p-4">
          <div className="flex items-center justify-between">
            <Button type="button" size="icon" variant="ghost" aria-label="上个月" onClick={() => moveMonth(-1)}><ChevronLeft aria-hidden="true" /></Button>
            <p className="font-semibold">{format(parseISO(`${month}-01`), "yyyy年M月")}</p>
            <Button type="button" size="icon" variant="ghost" aria-label="下个月" disabled={month >= today.slice(0, 7)} onClick={() => moveMonth(1)}><ChevronRight aria-hidden="true" /></Button>
          </div>
          {records.isLoading ? <p role="status">加载记录…</p> : records.error ? <p role="alert">{records.error.message}</p> : <MonthCalendar month={month} selected={selectedDate} today={today} recordedDates={recordedDates} onSelect={selectDate} />}
        </CardContent>
      </Card>

      {records.isSuccess && (selectedRecord ? (
        <RecordDetail record={selectedRecord} canEdit canManage={isAdmin} onManage={() => { setAuditTarget({ date: selectedRecord.date, recordId: selectedRecord.id }); setAdminOpen(true); }} />
      ) : (
        <Card><CardContent className="grid gap-3 p-4"><p>{format(parseISO(selectedDate), "yyyy年M月d日")}尚未记录</p><div className="flex flex-wrap gap-2"><Button asChild className="w-fit"><Link to={`/ledger?date=${selectedDate}`}>补记这一天</Link></Button>{isAdmin && <Button type="button" variant="outline" onClick={() => { setAuditTarget({ date: selectedDate, recordId: null }); setAdminOpen(true); }}>管理这天审计</Button>}</div></CardContent></Card>
      ))}

      <Dialog open={adminOpen} onOpenChange={setAdminOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle>管理 {auditTarget?.date ?? selectedDate} 记录</DialogTitle></DialogHeader>
          <div className="grid gap-4">
            {selectedRecord && selectedRecord.date === auditTarget?.date && <Button type="button" variant="destructive" className="w-fit" onClick={() => setDeleting(selectedRecord)}>删除这天记录</Button>}
            <div><h3 className="font-medium">修改历史</h3>
              {history.isLoading ? <p role="status">加载修改历史…</p> : history.error ? <div role="alert"><span>{history.error.message}</span><button className="ml-2 underline" onClick={() => void history.refetch()}>重试历史记录</button></div> : selectedHistory.length ? selectedHistory.map((entry) => (
                <div key={entry.id} className="flex items-center justify-between gap-2 border-b py-2 text-sm"><span>{entry.operation_type} · {entry.operator_username}</span>{entry.rollbackable !== false ? <Button size="sm" variant="outline" onClick={() => setRolling(entry)}>回滚 #{entry.id}</Button> : <span className="text-muted-foreground">不可回滚</span>}</div>
              )) : <p className="text-sm text-muted-foreground">暂无修改历史</p>}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog open={Boolean(deleting)} onOpenChange={(open) => { if (!open) setDeleting(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>确认删除记录？</AlertDialogTitle><AlertDialogDescription>删除后可通过历史记录回滚。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => deleting && remove.mutate({ storeId: selected.id, date: deleting.date })}>确认删除</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
      <AlertDialog open={Boolean(rolling)} onOpenChange={(open) => { if (!open) setRolling(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>确认回滚记录？</AlertDialogTitle><AlertDialogDescription>记录将恢复到该历史版本。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => rolling && rollback.mutate({ storeId: selected.id, auditId: rolling.id })}>确认回滚</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
      {message && <p role={message === "操作成功" ? "status" : "alert"}>{message}</p>}
    </section>
  );
}
