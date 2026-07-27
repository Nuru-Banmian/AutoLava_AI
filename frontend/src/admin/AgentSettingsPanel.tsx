import { useMutation, useQuery } from "@tanstack/react-query";

import { ApiError, api } from "@/api/client";
import type { AgentStatus } from "@/api/types";

const agentSettingsKey = ["admin", "agent-settings"] as const;

export function AgentSettingsPanel({ isOwner }: { isOwner: boolean }) {
  const settings = useQuery({
    queryKey: agentSettingsKey,
    queryFn: () => api<AgentStatus>("/admin/agent-settings"),
  });
  const update = useMutation({
    mutationFn: (enabled: boolean) =>
      api<AgentStatus>("/admin/agent-settings", {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: (next) => settings.refetch().then(() => next),
  });
  const enabled = update.data?.enabled ?? settings.data?.enabled ?? false;
  const releaseApproved = update.data?.release_approved ?? settings.data?.release_approved ?? false;

  return (
    <section
      aria-labelledby="agent-settings-title"
      className="space-y-3 rounded-xl border bg-card p-5 shadow-sm"
    >
      <div>
        <h2 className="font-medium" id="agent-settings-title">
          Agent 全局开关
        </h2>
        <p className="text-sm text-muted-foreground">
          关闭只会隐藏 Agent 并拒绝 Agent 请求，不影响其他业务功能。
        </p>
      </div>
      {settings.isPending ? (
        <p role="status">正在获取 Agent 设置…</p>
      ) : settings.isError ? (
        <p role="alert">Agent 设置暂时无法获取</p>
      ) : (
        <>
          <button
            aria-checked={enabled}
            aria-label="全局启用 Agent"
            className="inline-flex items-center gap-3 rounded-md border px-3 py-2 text-sm disabled:opacity-60"
            disabled={!isOwner || !releaseApproved || update.isPending}
            onClick={() => update.mutate(!enabled)}
            role="switch"
            type="button"
          >
            <span
              aria-hidden="true"
              className={`h-5 w-9 rounded-full p-0.5 ${enabled ? "bg-primary" : "bg-muted"}`}
            >
              <span
                className={`block h-4 w-4 rounded-full bg-white transition-transform ${enabled ? "translate-x-4" : ""}`}
              />
            </span>
            {enabled ? "已启用" : "已关闭"}
          </button>
          {!isOwner && <p className="text-sm text-muted-foreground">仅最终管理员可以修改此设置</p>}
          {!releaseApproved && (
            <p className="text-sm text-amber-700">生产发布门禁尚未通过，Agent 保持全局关闭</p>
          )}
          {update.isSuccess && (
            <p className="text-sm text-emerald-700" role="status">
              Agent 已全局{enabled ? "启用" : "关闭"}
            </p>
          )}
          {update.error && (
            <p className="text-sm text-destructive" role="alert">
              {update.error instanceof ApiError ? update.error.detail : "Agent 设置保存失败"}
            </p>
          )}
        </>
      )}
    </section>
  );
}
