import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, ApiError, friendlyApiError } from "@/api/client";
import type { RecordSnapshot } from "@/api/types";
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { invalidateUserData } from "@/lib/user-api";

interface DeleteScope {
  storeId: number;
  date: string;
  identity: string;
  revision: number;
}

export interface DeleteRecordDialogProps {
  storeId: number;
  record: RecordSnapshot | null;
  open: boolean;
  returnFocusTo?: HTMLButtonElement | null;
  onOpenChange(open: boolean): void;
  onCompleted(): void;
}

export function DeleteRecordDialog({ storeId, record, open, returnFocusTo, onOpenChange, onCompleted }: DeleteRecordDialogProps) {
  const client = useQueryClient();
  const [message, setMessage] = useState("");
  const targetDate = record?.date ?? null;
  const currentScope = useRef<DeleteScope>({ storeId, date: targetDate ?? "", identity: record?.identity ?? "", revision: record?.revision ?? 0 });
  currentScope.current = { storeId, date: targetDate ?? "", identity: record?.identity ?? "", revision: record?.revision ?? 0 };
  const [latest, setLatest] = useState<RecordSnapshot | null | undefined>(undefined);
  const deletionCompleted = useRef(false);

  useEffect(() => {
    if (open) { setMessage(""); setLatest(undefined); deletionCompleted.current = false; }
  }, [open, targetDate]);

  const matchesCurrentScope = (scope: DeleteScope) => (
    currentScope.current.storeId === scope.storeId
    && currentScope.current.date === scope.date
  );

  const remove = useMutation({
    mutationFn: (scope: DeleteScope) => api<void>(`/ledger/${scope.storeId}/${scope.date}`, { method: "DELETE", body: JSON.stringify({ expected_identity: scope.identity, expected_revision: scope.revision }) }),
    onSuccess: async (_data, scope) => {
      if (matchesCurrentScope(scope)) {
        deletionCompleted.current = true;
        setMessage("删除成功");
        onOpenChange(false);
      }
      await invalidateUserData(client, scope.storeId);
      if (deletionCompleted.current && currentScope.current.storeId === scope.storeId) onCompleted();
    },
    onError: (error, scope) => {
      if (!matchesCurrentScope(scope)) return;
      const detail = error instanceof ApiError && typeof error.responseBody === "object" && error.responseBody !== null && "detail" in error.responseBody ? error.responseBody.detail : null;
      if (error instanceof ApiError && error.status === 409 && typeof detail === "object" && detail !== null && "code" in detail && detail.code === "ledger_revision_conflict") {
        setLatest("current" in detail ? detail.current as RecordSnapshot | null : null);
        setMessage("记录已变化，删除已取消。请核对最新记录后重新打开删除确认。");
      } else if (error instanceof ApiError && (error.status === 401 || error.status === 403)) setMessage("当前没有删除权限，请重新登录或联系管理员。");
      else if (error instanceof ApiError && (error.status === 422 || error.status === 428)) setMessage("删除参数有误，请重新加载记录后再试。");
      else setMessage(friendlyApiError(error, "删除失败，请重试"));
    },
  });
  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && remove.isPending) return;
    onOpenChange(nextOpen);
  };

  return <>
    {record && <AlertDialog open={open} onOpenChange={handleOpenChange}>
      <AlertDialogContent onCloseAutoFocus={(event) => {
        event.preventDefault();
        if (!deletionCompleted.current) returnFocusTo?.focus();
      }}>
        <AlertDialogHeader>
          <AlertDialogTitle>确认永久删除记录？</AlertDialogTitle>
          <AlertDialogDescription>删除后无法恢复。</AlertDialogDescription>
        </AlertDialogHeader>
        {message && message !== "删除成功" && <p role="alert">{message}</p>}
        {latest !== undefined && <div role="status">{latest ? <><p>{`最新记录：${latest.is_open}，营业额 ${latest.daily_revenue} 欧元，修订号 ${latest.revision}`}</p><p>洗车数量：{latest.wash_count ?? "未记录"}；天气：{latest.weather ?? "未记录"}</p><p>事件：{latest.activity ?? "无"}</p></> : "最新记录：该日期暂无记录。"}</div>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={remove.isPending}>取消</AlertDialogCancel>
          <Button type="button" variant="destructive" disabled={remove.isPending || latest !== undefined || !record.identity || !record.revision} onClick={() => remove.mutate({ storeId, date: record.date, identity: record.identity!, revision: record.revision! })}>
            {remove.isPending ? "正在删除…" : "确认永久删除"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>}
    {message === "删除成功" && <p role="status">{message}</p>}
  </>;
}
