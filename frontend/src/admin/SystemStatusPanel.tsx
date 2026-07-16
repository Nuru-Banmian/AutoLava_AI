import { useQueries, useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { api } from "@/api/client";
import type { AdminStore, BriefingCard, ScheduledTaskLog, SystemAlert } from "@/api/types";
import { dashboardKey } from "@/lib/user-api";

type ParsedTimestamp = { value: string; epoch: number };

function parseTimestamp(value: string | null | undefined): ParsedTimestamp | null {
  if (!value || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
  const epoch = new Date(value).getTime();
  return Number.isNaN(epoch) ? null : { value, epoch };
}

function latestTimestamp(values: Array<string | null | undefined>) {
  return values.map(parseTimestamp).filter((value): value is ParsedTimestamp => value !== null)
    .sort((left, right) => right.epoch - left.epoch)[0] ?? null;
}

function hasNaiveTimestamp(values: Array<string | null | undefined>) {
  return values.some((value) => Boolean(value) && !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value!));
}

type TimestampIssue = "legacy" | "invalid" | null;

function formatTimestamp(value: ParsedTimestamp | null, issue: TimestampIssue = null) {
  const issueText = issue === "legacy" ? "历史时间时区未知" : issue === "invalid" ? "时间格式缺少时区" : null;
  if (!value) return issueText ?? "暂无记录";
  const formatted = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
    hourCycle: "h23", timeZone: "UTC", timeZoneName: "short",
  }).format(new Date(value.epoch));
  return issueText ? `${formatted}；另有${issueText}` : formatted;
}

export function SystemStatusPanel() {
  const stores = useQuery({ queryKey: ["admin", "stores"], queryFn: () => api<AdminStore[]>("/admin/stores") });
  const alerts = useQuery({ queryKey: ["admin", "alerts"], queryFn: () => api<SystemAlert[]>("/admin/alerts") });
  const taskLogs = useQuery({ queryKey: ["admin", "task-logs"], queryFn: () => api<ScheduledTaskLog[]>("/admin/task-logs") });
  const dashboardQueries = useQueries({ queries: (stores.data ?? []).filter((store) => store.is_active).map((store) => ({
    queryKey: dashboardKey(store.id),
    queryFn: () => api<BriefingCard[]>(`/dashboard/${store.id}`),
  })) });
  const activeStores = (stores.data ?? []).filter((store) => store.is_active);
  const dashboardStates = activeStores.map((store, index) => {
    const cards = dashboardQueries[index]?.data ?? [];
    const utcValues = cards.filter((card) => card.timestamp_status === "utc").map((card) => card.generated_at);
    const hasLegacy = cards.some((card) => card.timestamp_status !== "utc");
    const hasInvalid = utcValues.some((value) => parseTimestamp(value) === null);
    return { store, latest: latestTimestamp(utcValues), issue: hasLegacy ? "legacy" as const : hasInvalid ? "invalid" as const : null };
  });
  const dashboardCards = dashboardQueries.flatMap((query) => query.data ?? []);
  const dashboardGeneratedAt = latestTimestamp(dashboardStates.map((state) => state.latest?.value));
  const dashboardIssue = dashboardStates.some((state) => state.issue === "legacy") ? "legacy" : dashboardStates.some((state) => state.issue === "invalid") ? "invalid" : null;
  const weatherTasks = (taskLogs.data ?? []).filter((task) => task.task_type.toLowerCase().includes("weather"));
  const weatherTaskTimes = weatherTasks.filter((task) => task.timestamp_status === "utc").map((task) => ({
    task,
    raw: task.finished_at ?? task.started_at ?? task.created_at,
    parsed: parseTimestamp(task.finished_at ?? task.started_at ?? task.created_at),
  }));
  const latestWeather = weatherTaskTimes.filter((entry) => entry.parsed !== null)
    .sort((left, right) => right.parsed!.epoch - left.parsed!.epoch)[0] ?? null;
  const weatherIssue = weatherTasks.some((task) => task.timestamp_status !== "utc")
    ? "legacy"
    : hasNaiveTimestamp(weatherTaskTimes.map((entry) => entry.raw)) ? "invalid" : null;
  const unresolvedAlerts = (alerts.data ?? []).filter((alert) => !alert.is_resolved);
  const alertTimestampsInvalid = (alerts.data ?? []).some((alert) => alert.timestamp_status !== "utc"
    || parseTimestamp(alert.created_at) === null
    || (alert.resolved_at !== null && parseTimestamp(alert.resolved_at) === null));
  const taskTimestampsInvalid = (taskLogs.data ?? []).some((task) => task.timestamp_status !== "utc"
    || parseTimestamp(task.started_at) === null
    || parseTimestamp(task.created_at) === null
    || (task.finished_at !== null && parseTimestamp(task.finished_at) === null));
  const hasUnresolvedError = unresolvedAlerts.some((alert) => alert.level.toLowerCase() === "error");
  const latestWeatherFailed = latestWeather !== null && latestWeather.task.status.toLowerCase() !== "success";
  const loading = stores.isPending || alerts.isPending || taskLogs.isPending || dashboardQueries.some((query) => query.isPending);
  const failed = stores.isError || alerts.isError || taskLogs.isError || dashboardQueries.some((query) => query.isError);
  const empty = stores.isSuccess && alerts.isSuccess && taskLogs.isSuccess
    && activeStores.length === 0 && alerts.data.length === 0 && taskLogs.data.length === 0 && dashboardCards.length === 0;
  const everyStoreHasDashboard = activeStores.length > 0 && dashboardStates.every((state) => state.latest !== null && state.issue === null);
  const requiredTimestampsValid = !alertTimestampsInvalid && !taskTimestampsInvalid && dashboardIssue === null;
  const complete = latestWeather !== null && everyStoreHasDashboard && requiredTimestampsValid;

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
        <div><dt className="text-muted-foreground">最近天气更新</dt><dd>{formatTimestamp(latestWeather?.parsed ?? null, weatherIssue)}</dd></div>
        <div><dt className="text-muted-foreground">最近仪表盘生成</dt><dd>{formatTimestamp(dashboardGeneratedAt, dashboardIssue)}</dd></div>
        <div className="sm:col-span-2"><dt className="text-muted-foreground">各门店仪表盘</dt><dd><ul>{dashboardStates.map((state) => <li key={state.store.id}>{state.store.name}：{formatTimestamp(state.latest, state.issue)}</li>)}</ul></dd></div>
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
