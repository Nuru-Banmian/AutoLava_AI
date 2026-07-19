import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api, friendlyApiError } from "@/api/client";
import type { RecordSnapshot } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { invalidateUserData } from "@/lib/user-api";

interface DeleteScope {
  storeId: number;
  date: string;
}

export interface RecordManagementDialogsProps {
  storeId: number;
  record: RecordSnapshot | null;
  open: boolean;
  onOpenChange(open: boolean): void;
  onCompleted(): void;
}

export function RecordManagementDialogs({ storeId, record, open, onOpenChange, onCompleted }: RecordManagementDialogsProps) {
  const { user } = useAuth();
  const client = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [deleting, setDeleting] = useState(false);
  const [message, setMessage] = useState("");
  const targetDate = record?.date ?? null;
  const currentScope = useRef<DeleteScope>({ storeId, date: targetDate ?? "" });
  currentScope.current = { storeId, date: targetDate ?? "" };

  const matchesCurrentScope = (scope: DeleteScope) => (
    currentScope.current.storeId === scope.storeId
    && currentScope.current.date === scope.date
  );

  const remove = useMutation({
    mutationFn: (scope: DeleteScope) => api<void>(`/ledger/${scope.storeId}/${scope.date}`, { method: "DELETE" }),
    onSuccess: async (_data, scope) => {
      if (matchesCurrentScope(scope)) {
        setDeleting(false);
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

  if (!isAdmin || !targetDate) return null;

  return <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>管理 {targetDate} 记录</DialogTitle></DialogHeader>
        {record
          ? <Button type="button" variant="destructive" className="w-fit" onClick={() => { setMessage(""); setDeleting(true); }}>永久删除这天记录</Button>
          : <p className="text-sm text-muted-foreground">这一天没有可管理的记录。</p>}
      </DialogContent>
    </Dialog>
    <AlertDialog open={deleting} onOpenChange={(nextOpen) => { if (!nextOpen) setDeleting(false); }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>确认永久删除记录？</AlertDialogTitle>
          <AlertDialogDescription>删除后无法恢复。</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <Button type="button" variant="destructive" disabled={remove.isPending} onClick={() => record && remove.mutate({ storeId, date: record.date })}>确认永久删除</Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    {message && <p role={message === "删除成功" ? "status" : "alert"}>{message}</p>}
  </>;
}
