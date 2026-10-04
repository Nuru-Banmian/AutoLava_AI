import { useState } from "react";

import { friendlyApiError } from "@/api/client";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { downloadDatabaseBackup } from "@/lib/database-backup";

export function DatabaseBackupPanel() {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");

  async function download() {
    setDownloading(true);
    setError("");
    try {
      await downloadDatabaseBackup();
    } catch (downloadError) {
      setError(friendlyApiError(downloadError, "数据库备份下载失败，请重试"));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <section
      className="min-w-0 space-y-4 rounded-xl border border-border bg-card p-4 shadow-sm [overflow-wrap:anywhere] sm:p-5"
      aria-labelledby="database-backup-title"
    >
      <div className="space-y-2">
        <h2 className="text-lg font-semibold" id="database-backup-title">数据库备份</h2>
        <p className="text-sm leading-6 text-muted-foreground">
          生成当前数据库的一致快照，用于离线保管。
        </p>
      </div>
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button type="button" disabled={downloading}>
            {downloading ? "正在准备备份…" : "下载数据库备份"}
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>下载完整数据库备份？</AlertDialogTitle>
            <AlertDialogDescription>
              该文件包含完整经营数据、账号信息和密码哈希。请只保存到受保护的位置，
              不要通过不安全的渠道传输。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={() => void download()}>
              确认并下载
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {error && <p role="alert" className="text-sm leading-6 text-destructive">{error}</p>}
    </section>
  );
}
