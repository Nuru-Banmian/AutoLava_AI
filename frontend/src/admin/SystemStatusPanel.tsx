import { useQueries, useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { api } from "@/api/client";
import type { AdminStore, BriefingCard, ScheduledTaskLog, SystemAlert } from "@/api/types";
import { dashboardKey } from "@/lib/user-api";

function latestTimestamp(values: Array<string | null | undefined>) {
  return values.filter((value): value is string => Boolean(value)).sort().at(-1) ?? null;
}

function formatTimestamp(value: string | null) {
  if (!value) return "暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function SystemStatusPanel() {
  const stores = useQuery({ queryKey: ["admin", "stores"], queryFn: () => api<AdminStore[]>("/admin/stores") });
  const alerts = useQuery({ queryKey: ["admin", "alerts"], queryFn: () => api<SystemAlert[]>("/admin/alerts") });
  const taskLogs = useQuery({ queryKey: ["admin", "task-logs"], queryFn: () => api<ScheduledTaskLog[]>("/admin/task-logs") });
  const dashboardQueries = useQueries({ queries: (stores.data ?? []).filter((store) => store.is_active).map((store) => ({
    queryKey: dashboardKey(store.id),
    queryFn: () => api<BriefingCard[]>(`/dashboard/${store.id}`),
  })) });
  const dashboardCards = dashboardQueries.flatMap((query) => query.data ?? []);
  const dashboardGeneratedAt = latestTimestamp(dashboardCards.map((card) => card.generated_at));
  const weatherTasks = (taskLogs.data ?? []).filter((task) => task.task_type.toLowerCase().includes("weather"));
  const latestWeatherTask = [...weatherTasks].sort((left, right) => {
    const leftTime = left.finished_at ?? left.started_at ?? left.created_at;
    const rightTime = right.finished_at ?? right.started_at ?? right.created_at;
    return rightTime.localeCompare(leftTime);
  })[0];
  const weatherUpdatedAt = latestWeatherTask?.finished_at ?? latestWeatherTask?.started_at ?? latestWeatherTask?.created_at ?? null;
  const unresolvedAlerts = (alerts.data ?? []).filter((alert) => !alert.is_resolved);
  const hasUnresolvedError = unresolvedAlerts.some((alert) => alert.level.toLowerCase() === "error");
  const latestWeatherFailed = latestWeatherTask !== undefined && latestWeatherTask.status.toLowerCase() !== "success";
  const loading = stores.isPending || alerts.isPending || taskLogs.isPending || dashboardQueries.some((query) => query.isPending);
  const failed = stores.isError || alerts.isError || taskLogs.isError || dashboardQueries.some((query) => query.isError);
  const empty = stores.isSuccess && alerts.isSuccess && taskLogs.isSuccess
    && alerts.data.length === 0 && taskLogs.data.length === 0 && dashboardCards.length === 0;
  const complete = Boolean(weatherUpdatedAt && dashboardGeneratedAt);

  let summary: ReactNode;
  if (loading) summary = <p role="status">正在获取系统状态…</p>;
  else if (failed) summary = <p role="alert" className="text-destructive">状态暂时无法获取，请稍后重试</p>;
  else if (empty) summary = <p role="status">暂无可用状态数据</p>;
  else if (hasUnresolvedError) summary = <p role="alert" className="text-destructive">系统存在未解决错误</p>;
  else if (!complete) summary = <p role="status">状态数据不完整</p>;
  else if (latestWeatherFailed) summary = <p role="alert" className="text-destructive">最近天气任务未成功</p>;
  else summary = <p role="status" className="text-emerald-700">运行正常</p>;

  return <div className="space-y-4">
    <section className="space-y-2 rounded-lg border bg-card p-4" aria-labelledby="status-summary-title">
      <h2 className="font-medium" id="status-summary-title">运行状态</h2>
      {summary}
      {!loading && !failed && <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div><dt className="text-muted-foreground">最近天气更新</dt><dd>{formatTimestamp(weatherUpdatedAt)}</dd></div>
        <div><dt className="text-muted-foreground">最近仪表盘生成</dt><dd>{formatTimestamp(dashboardGeneratedAt)}</dd></div>
      </dl>}
    </section>
    {!loading && !failed && <section className="space-y-2 rounded-lg border p-4" aria-labelledby="unresolved-alerts-title">
      <h2 className="font-medium" id="unresolved-alerts-title">未解决告警（{unresolvedAlerts.length}）</h2>
      {unresolvedAlerts.length === 0
        ? <p className="text-sm text-muted-foreground">当前没有未解决告警</p>
        : <ul className="space-y-2">{unresolvedAlerts.map((item) => <li className="rounded-md bg-muted/40 p-3 text-sm" key={item.id}><span className="font-medium">{item.level}</span> · {item.message}</li>)}</ul>}
    </section>}
  </div>;
}
