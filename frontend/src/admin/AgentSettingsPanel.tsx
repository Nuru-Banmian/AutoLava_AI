import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, friendlyApiError } from "@/api/client";
import type { AgentSettings } from "@/api/types";

export const agentSettingsKey = ["agent", "admin", "settings"] as const;

export function AgentSettingsPanel() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: agentSettingsKey,
    queryFn: () => api<AgentSettings>("/agent/admin/settings"),
    retry: false,
  });
  const update = useMutation({
    mutationFn: (enabled: boolean) => api<AgentSettings>("/agent/admin/settings", {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),
    onSuccess: async (value) => {
      queryClient.setQueryData(agentSettingsKey, value);
      await queryClient.invalidateQueries({ queryKey: ["agent", "store"] });
    },
  });

  return (
    <section
      aria-labelledby="agent-settings-title"
      className="space-y-3 rounded-xl border bg-card p-5 shadow-sm"
    >
      <div>
        <h2 className="font-medium" id="agent-settings-title">数据分析 Agent</h2>
        <p className="text-sm text-muted-foreground">
          模型连接由部署环境管理；这里不显示或保存任何连接信息。
        </p>
      </div>
      {settings.isPending && <p role="status">正在读取 Agent 配置…</p>}
      {settings.isError && (
        <p className="text-sm text-destructive" role="alert">
          {friendlyApiError(settings.error, "Agent 配置暂时无法读取")}
        </p>
      )}
      {settings.data && (
        <>
          <p className="text-sm">
            {settings.data.model_config_ready ? "模型配置已就绪" : "模型配置不完整"}
          </p>
          <label className="flex items-center gap-3 text-sm font-medium">
            <input
              aria-label="全系统启用数据分析 Agent"
              checked={settings.data.enabled}
              disabled={
                update.isPending
                || (!settings.data.enabled && !settings.data.model_config_ready)
              }
              onChange={(event) => update.mutate(event.target.checked)}
              type="checkbox"
            />
            全系统启用数据分析 Agent
          </label>
          <p className="text-sm" role="status">
            数据分析 Agent {settings.data.enabled ? "已启用" : "已关闭"}
          </p>
        </>
      )}
      {update.isError && (
        <p className="text-sm text-destructive" role="alert">
          {friendlyApiError(update.error, "Agent 开关保存失败，请重试")}
        </p>
      )}
    </section>
  );
}
