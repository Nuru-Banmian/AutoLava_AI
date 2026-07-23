import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, friendlyApiError } from "@/api/client";
import type { RecordSnapshot } from "@/api/types";
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { invalidateUserData } from "@/lib/user-api";

interface DeleteScope {
  storeId: number;
  date: string;
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
  const currentScope = useRef<DeleteScope>({ storeId, date: targetDate ?? "" });
  currentScope.current = { storeId, date: targetDate ?? "" };

  useEffect(() => {
    if (open) setMessage("");
  }, [open, targetDate]);

  const matchesCurrentScope = (scope: DeleteScope) => (
    currentScope.current.storeId === scope.storeId
    && currentScope.current.date === scope.date
  );

  const remove = useMutation({
    mutationFn: (scope: DeleteScope) => api<void>(`/ledger/${scope.storeId}/${scope.date}`, { method: "DELETE" }),
    onSuccess: async (_data, scope) => {
      if (matchesCurrentScope(scope)) {
        setMessage("删除成功");
        onOpenChange(false);
        onCompleted();
      }
      await invalidateUserData(client, scope.storeId);
    },
    onError: (error, scope) => {
      if (matchesCurrentScope(scope)) setMessage(friendlyApiError(error, "删除失败，请重试"));
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
        returnFocusTo?.focus();
      }}>
        <AlertDialogHeader>
          <AlertDialogTitle>确认永久删除记录？</AlertDialogTitle>
          <AlertDialogDescription>删除后无法恢复。</AlertDialogDescription>
        </AlertDialogHeader>
        {message && message !== "删除成功" && <p role="alert">{message}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={remove.isPending}>取消</AlertDialogCancel>
          <Button type="button" variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate({ storeId, date: record.date })}>
            {remove.isPending ? "正在删除…" : "确认永久删除"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>}
    {message === "删除成功" && <p role="status">{message}</p>}
  </>;
}
