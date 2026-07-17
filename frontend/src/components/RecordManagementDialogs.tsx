import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api, ApiError, friendlyApiError } from "@/api/client";
import type { AuditEntry, RecordSnapshot } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { invalidateUserData } from "@/lib/user-api";

interface AuditPageResponse {
  items: AuditEntry[];
  total: number;
  page: number;
  page_size: number;
}

interface MutationScope {
  storeId: number;
  date: string;
  version: number | null;
}

export interface RecordManagementDialogsProps {
  storeId: number;
  record: RecordSnapshot | null;
  targetDate: string | null;
  open: boolean;
  onOpenChange(open: boolean): void;
  onCompleted(): void;
}

export function RecordManagementDialogs({ storeId, record, targetDate, open, onOpenChange, onCompleted }: RecordManagementDialogsProps) {
  const { user } = useAuth();
  const client = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [deleting, setDeleting] = useState<RecordSnapshot | null>(null);
  const [deleteConflict, setDeleteConflict] = useState(false);
  const [rolling, setRolling] = useState<AuditEntry | null>(null);
  const [message, setMessage] = useState("");
  const currentScope = useRef<MutationScope>({ storeId, date: targetDate ?? "", version: record?.row_version ?? null });
  currentScope.current = { storeId, date: targetDate ?? "", version: record?.row_version ?? null };

  const history = useQuery({
    queryKey: ["database", "history", storeId, record?.id ?? null, targetDate],
    enabled: Boolean(isAdmin && open && targetDate),
    queryFn: () => {
      const params = record
        ? new URLSearchParams({ record_id: String(record.id) })
        : new URLSearchParams({ record_date: targetDate!, page_size: "100" });
      return api<AuditPageResponse>(`/database/${storeId}/history?${params}`);
    },
  });
  const selectedHistory = history.data?.items.filter((entry) => entry.record_date === targetDate) ?? [];
  const matchesCurrentScope = (scope: MutationScope) => (
    currentScope.current.storeId === scope.storeId
    && currentScope.current.date === scope.date
    && currentScope.current.version === scope.version
  );
  const invalidate = async (scope: MutationScope) => {
    await invalidateUserData(client, scope.storeId);
    await client.invalidateQueries({ queryKey: ["database", "history", scope.storeId] });
  };
  const finish = async (scope: MutationScope) => {
    if (matchesCurrentScope(scope)) {
      setMessage("操作成功");
      setDeleting(null);
      setDeleteConflict(false);
      setRolling(null);
      onCompleted();
    }
    await invalidate(scope);
  };

  const remove = useMutation({
    mutationFn: (scope: MutationScope) => api<void>(`/ledger/${scope.storeId}/${scope.date}?expected_version=${scope.version}`, { method: "DELETE" }),
    onSuccess: (_data, scope) => finish(scope),
    onError: (error, scope) => {
      if (!matchesCurrentScope(scope)) return;
      const isConflict = error instanceof ApiError && error.status === 409;
      setDeleteConflict(isConflict);
      if (!isConflict) onOpenChange(false);
      setMessage(friendlyApiError(error, "删除失败，请重试"));
    },
  });
  const rollback = useMutation({
    mutationFn: ({ auditId, ...scope }: MutationScope & { auditId: number }) => api(`/database/${scope.storeId}/history/${auditId}/rollback`, { method: "POST" }),
    onSuccess: (_data, { auditId: _auditId, ...scope }) => finish(scope),
    onError: (error, { auditId: _auditId, ...scope }) => {
      if (matchesCurrentScope(scope)) setMessage(error instanceof ApiError ? error.detail : "回滚失败");
    },
  });
  const reloadDeleteRecord = async () => {
    if (!deleting || !targetDate) return;
    await invalidate({ storeId, date: targetDate, version: deleting.row_version });
    if (currentScope.current.storeId === storeId && currentScope.current.date === targetDate) {
      setDeleteConflict(false);
      setMessage("");
    }
  };
  const closeDelete = (nextOpen: boolean) => {
    if (nextOpen) return;
    setDeleting(null);
    setDeleteConflict(false);
  };

  if (!isAdmin || !targetDate) return null;

  return <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader><DialogTitle>管理 {targetDate} 记录</DialogTitle></DialogHeader>
        <div className="grid gap-4">
          {record?.date === targetDate && <Button type="button" variant="destructive" className="w-fit" onClick={() => { setDeleteConflict(false); setMessage(""); setDeleting(record); }}>删除这天记录</Button>}
          <div><h3 className="font-medium">修改历史</h3>
            {history.isLoading ? <p role="status">加载修改历史…</p> : history.error ? <div role="alert"><span>{history.error.message}</span><button type="button" className="ml-2 underline" onClick={() => void history.refetch()}>重试历史记录</button></div> : selectedHistory.length ? selectedHistory.map((entry) => (
              <div key={entry.id} className="flex items-center justify-between gap-2 border-b py-2 text-sm"><span>{entry.operation_type} · {entry.operator_username}</span>{entry.rollbackable !== false ? <Button size="sm" variant="outline" onClick={() => setRolling(entry)}>回滚 #{entry.id}</Button> : <span className="text-muted-foreground">不可回滚</span>}</div>
            )) : <p className="text-sm text-muted-foreground">暂无修改历史</p>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
    <AlertDialog open={Boolean(deleting)} onOpenChange={closeDelete}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>确认删除记录？</AlertDialogTitle><AlertDialogDescription role={deleteConflict ? "alert" : undefined}>{deleteConflict ? "数据已经发生变化，请刷新后重试。重新加载后请确认最新内容。" : "删除后可通过历史记录回滚。"}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel>{deleteConflict && <Button type="button" variant="outline" onClick={() => void reloadDeleteRecord()}>重新加载记录</Button>}<Button type="button" variant="destructive" onClick={() => deleting && remove.mutate({ storeId, date: deleting.date, version: deleting.row_version })}>确认删除</Button></AlertDialogFooter></AlertDialogContent>
    </AlertDialog>
    <AlertDialog open={Boolean(rolling)} onOpenChange={(nextOpen) => { if (!nextOpen) setRolling(null); }}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>确认回滚记录？</AlertDialogTitle><AlertDialogDescription>记录将恢复到该历史版本。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => rolling && rollback.mutate({ storeId, date: targetDate, version: record?.row_version ?? null, auditId: rolling.id })}>确认回滚</AlertDialogAction></AlertDialogFooter></AlertDialogContent>
    </AlertDialog>
    {message && <p role={message === "操作成功" ? "status" : "alert"}>{message}</p>}
  </>;
}
