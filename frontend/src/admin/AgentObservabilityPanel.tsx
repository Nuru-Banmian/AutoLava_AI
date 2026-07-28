import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "@/api/client";
import type { AgentAlert, AgentRunStat } from "@/api/types";

const runsKey = ["admin", "agent-observability", "runs"] as const;
const alertsKey = ["admin", "agent-observability", "alerts"] as const;

function tokenCount(value: number | null) {
  return value === null ? "未知" : value.toLocaleString("zh-CN");
}

function cost(value: number | null) {
  return value === null ? "未知" : `€${value.toFixed(4)}`;
}

function timestamp(value: string) {
  return value.replace("T", " ");
}

export function AgentObservabilityPanel() {
  const queryClient = useQueryClient();
  const runs = useQuery({
    queryKey: runsKey,
    queryFn: () => api<AgentRunStat[]>("/admin/agent-observability/runs"),
  });
  const alerts = useQuery({
    queryKey: alertsKey,
    queryFn: () => api<AgentAlert[]>("/admin/agent-observability/alerts"),
  });
  const updateAlert = useMutation({
    mutationFn: ({ id, status }: { id: number; status: "open" | "resolved" }) =>
      api<AgentAlert>(`/admin/agent-observability/alerts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData<AgentAlert[]>(alertsKey, (current) =>
        (current ?? []).map((alert) => (alert.id === updated.id ? updated : alert)),
      );
    },
  });
  const loading = runs.isPending || alerts.isPending;
  const failed = runs.isError || alerts.isError;

  return (
    <section
      aria-labelledby="agent-observability-title"
      className="space-y-4 rounded-xl border bg-card p-5 shadow-sm"
    >
      <div>
        <h2 className="font-medium" id="agent-observability-title">
          Agent 运行健康
        </h2>
        <p className="text-sm text-muted-foreground">
          仅显示脱敏运行诊断，不包含问题、回答、提示词、工具 payload 或 SQL。
        </p>
      </div>
      {loading ? (
        <p role="status">正在获取 Agent 运行状态…</p>
      ) : failed ? (
        <p className="text-destructive" role="alert">
          Agent 运行状态暂时无法获取
        </p>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(20rem,0.65fr)]">
          <div className="min-w-0 space-y-3">
            <h3 className="font-medium">最近运行</h3>
            {runs.data.length === 0 ? (
              <p className="text-sm text-muted-foreground">还没有 Agent 运行统计</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[48rem] text-left text-sm">
                  <thead className="text-muted-foreground">
                    <tr>
                      <th className="pb-2 pr-3 font-medium">运行</th>
                      <th className="pb-2 pr-3 font-medium">阶段</th>
                      <th className="pb-2 pr-3 font-medium">供应商 / 模型</th>
                      <th className="pb-2 pr-3 font-medium">Token 输入 / 输出</th>
                      <th className="pb-2 pr-3 font-medium">结果</th>
                      <th className="pb-2 pr-3 font-medium">延迟</th>
                      <th className="pb-2 font-medium">费用</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.data.map((run) => (
                      <tr className="border-t align-top" key={run.id}>
                        <td className="break-all py-3 pr-3 font-mono">{run.run_id}</td>
                        <td className="py-3 pr-3">{run.stage}</td>
                        <td className="py-3 pr-3">
                          {run.provider} / {run.model}
                        </td>
                        <td className="py-3 pr-3">
                          {tokenCount(run.input_tokens)} / {tokenCount(run.output_tokens)}
                        </td>
                        <td className="py-3 pr-3">
                          <span>{run.result}</span>
                          {run.error_category && (
                            <span className="block text-muted-foreground">
                              {run.error_category}
                            </span>
                          )}
                          {run.is_fallback && (
                            <span className="block text-amber-700">已使用回退</span>
                          )}
                        </td>
                        <td className="py-3 pr-3">{run.latency_ms} ms</td>
                        <td className="py-3">{cost(run.estimated_cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <div className="space-y-3">
            <h3 className="font-medium">Agent 告警</h3>
            {alerts.data.length === 0 ? (
              <p className="text-sm text-muted-foreground">当前没有 Agent 告警</p>
            ) : (
              <ul className="space-y-3">
                {alerts.data.map((alert) => (
                  <li className="space-y-2 rounded-md bg-muted/40 p-3 text-sm" key={alert.id}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium">
                        {alert.alert_type} · {alert.error_category}
                      </span>
                      <span
                        className={alert.is_resolved ? "text-muted-foreground" : "text-amber-700"}
                      >
                        {alert.is_resolved ? "已解决" : "待处理"}
                      </span>
                    </div>
                    <p>{alert.message}</p>
                    <p className="text-muted-foreground">
                      {alert.provider} / {alert.model} · 累计 {alert.occurrence_count} 次
                    </p>
                    <p className="text-muted-foreground">
                      最近出现：{timestamp(alert.last_seen_at)}
                    </p>
                    <button
                      aria-label={`标记告警 ${alert.id} 为${alert.is_resolved ? "待处理" : "已解决"}`}
                      className="rounded-md border px-3 py-1.5 disabled:opacity-60"
                      disabled={updateAlert.isPending}
                      onClick={() =>
                        updateAlert.mutate({
                          id: alert.id,
                          status: alert.is_resolved ? "open" : "resolved",
                        })
                      }
                      type="button"
                    >
                      标记为{alert.is_resolved ? "待处理" : "已解决"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {updateAlert.error && (
              <p className="text-destructive" role="alert">
                {updateAlert.error instanceof ApiError
                  ? updateAlert.error.detail
                  : "Agent 告警状态保存失败"}
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
