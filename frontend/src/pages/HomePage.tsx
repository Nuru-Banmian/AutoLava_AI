import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { ApiError, api } from "@/api/client";
import type { BriefingCard } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { AgentPanel } from "@/components/AgentPanel";
import { BriefingCards } from "@/components/BriefingCards";
import { Button, buttonVariants } from "@/components/ui/button";
import { dashboardKey } from "@/lib/user-api";
import { useStore } from "@/stores/StoreProvider";

function dateInTimezone(timezone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

function addDays(value: string, amount: number) {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + amount);
  return date.toISOString().slice(0, 10);
}

export function HomePage() {
  const { user } = useAuth();
  const { selected } = useStore();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: selected ? dashboardKey(selected.id) : ["dashboard", "none"],
    enabled: Boolean(selected),
    queryFn: () => api<BriefingCard[]>(`/dashboard/${selected!.id}`),
  });
  const refresh = useMutation({
    mutationFn: (storeId: number) =>
      api<BriefingCard[]>(`/dashboard/${storeId}/refresh`, { method: "POST" }),
    onSuccess: async (cards, storeId) => {
      client.setQueryData(dashboardKey(storeId), cards);
      await client.invalidateQueries({ queryKey: dashboardKey(storeId), exact: true });
    },
  });
  useEffect(() => refresh.reset(), [selected?.id]);
  if (!selected)
    return (
      <section>
        <h1 className="text-2xl font-semibold">仪表盘</h1>
        <p role="status">请先选择门店。</p>
      </section>
    );
  const today = dateInTimezone(selected.timezone);
  const briefing =
    query.isLoading && !query.data ? (
      <p role="status">加载简报…</p>
    ) : query.error && !query.data ? (
      <p role="alert">{query.error.message}</p>
    ) : (
      <BriefingCards
        cards={query.data ?? []}
        compact={user?.role === "admin"}
        yesterdayHref={`/ledger?date=${addDays(today, -1)}`}
      />
    );
  const actions =
    selected.is_active !== false ? (
      <div className="flex flex-wrap gap-2">
        <a className={buttonVariants()} href={`/ledger?date=${today}`}>
          立即记账
        </a>
        <Button
          variant="outline"
          disabled={refresh.isPending}
          onClick={() => refresh.mutate(selected.id)}
        >
          刷新简报
        </Button>
      </div>
    ) : (
      <p role="status">该门店已归档，仅可查看历史数据和经营分析。</p>
    );

  if (user?.role === "admin") {
    return (
      <section className="grid min-w-0 gap-4">
        <header>
          <h1 className="text-2xl font-semibold">Agent 调查</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            围绕当前门店持续提问，并随时核对回答所依据的经营证据。
          </p>
        </header>
        <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
          <AgentPanel
            key={selected.id}
            className="lg:h-[calc(100dvh-8.5rem)] lg:min-h-[42rem]"
            storeId={selected.id}
            timezone={selected.timezone}
          />
          <aside
            aria-labelledby="briefing-title"
            className="grid min-w-0 gap-3 lg:max-h-[calc(100dvh-8.5rem)] lg:overflow-y-auto"
          >
            <div>
              <h2 className="text-lg font-semibold" id="briefing-title">
                经营简报
              </h2>
              <p className="text-sm text-muted-foreground">当前门店的日常概览</p>
            </div>
            {briefing}
            {actions}
            {refresh.error && refresh.variables === selected.id && (
              <p role="alert">
                {refresh.error instanceof ApiError ? refresh.error.detail : "刷新失败"}
              </p>
            )}
          </aside>
        </div>
      </section>
    );
  }

  return (
    <section className="grid gap-4">
      <header>
        <h1 className="text-2xl font-semibold">仪表盘</h1>
      </header>
      <section aria-label="每日简报">{briefing}</section>
      {actions}
      {refresh.error && refresh.variables === selected.id && (
        <p role="alert">{refresh.error instanceof ApiError ? refresh.error.detail : "刷新失败"}</p>
      )}
    </section>
  );
}
