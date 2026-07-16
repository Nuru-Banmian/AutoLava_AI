import { useQuery } from "@tanstack/react-query";

import { api, ApiError } from "@/api/client";
import type { ScheduledTaskLog, SystemAlert } from "@/api/types";

function ErrorMessage({ error }: { error: Error | null }) { if (!error) return null; return <p role="alert" className="text-sm text-destructive">{error instanceof ApiError ? error.detail : "请求失败"}</p>; }

export function SystemStatusPanel() {
  const alerts = useQuery({ queryKey: ["admin", "alerts"], queryFn: () => api<SystemAlert[]>("/admin/alerts") });
  const taskLogs = useQuery({ queryKey: ["admin", "task-logs"], queryFn: () => api<ScheduledTaskLog[]>("/admin/task-logs") });
  return <>
    <section><h2 className="font-medium">告警</h2><ErrorMessage error={alerts.error} /><ul>{alerts.data?.map((item) => <li key={item.id}>{item.level}: {item.message}</li>)}</ul></section>
    <section><h2 className="font-medium">任务日志</h2><ErrorMessage error={taskLogs.error} /><ul>{taskLogs.data?.map((item) => <li key={item.id}>{item.task_type}: {item.status}</li>)}</ul></section>
  </>;
}
