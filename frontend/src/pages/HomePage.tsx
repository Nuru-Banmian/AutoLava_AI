import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api, ApiError, friendlyApiError } from "@/api/client";
import type { BriefingCard } from "@/api/types";
import { BriefingCards } from "@/components/BriefingCards";
import { Button, buttonVariants } from "@/components/ui/button";
import { dashboardKey, formatWholeEuro, ledgerRecordKey, loadLedgerRecord, storeLocalToday } from "@/lib/user-api";
import { useStore } from "@/stores/StoreProvider";

function addDays(value: string, amount: number) {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + amount);
  return date.toISOString().slice(0, 10);
}

export function HomePage() {
  const { selected } = useStore();
  const client = useQueryClient();
  const today = selected ? storeLocalToday(selected) : "";
  const record = useQuery({
    queryKey: selected ? ledgerRecordKey(selected.id, today) : ["ledger", "record", "none"],
    enabled: Boolean(selected),
    queryFn: ({ signal }) => loadLedgerRecord(selected!.id, today, signal),
  });
  const query = useQuery({ queryKey: selected ? dashboardKey(selected.id) : ["dashboard", "none"], enabled: Boolean(selected), queryFn: ({ signal }) => api<BriefingCard[]>(`/dashboard/${selected!.id}`, { signal }) });
  const refresh = useMutation({ mutationFn: (storeId: number) => api<BriefingCard[]>(`/dashboard/${storeId}/refresh`, { method: "POST" }), onSuccess: async (cards, storeId) => { client.setQueryData(dashboardKey(storeId), cards); await client.invalidateQueries({ queryKey: dashboardKey(storeId), exact: true }); } });
  useEffect(() => refresh.reset(), [selected?.id]);
  if (!selected) return <section><h1 className="text-2xl font-semibold">首页</h1><p role="status">请先选择门店。</p></section>;
  const hasRecordResult = record.data !== undefined;
  return <section className="grid min-w-0 gap-4">
    <header><h1 className="text-2xl font-semibold">首页</h1></header>
    <section aria-label="今日状态" className="grid min-w-0 gap-4 rounded-xl border border-primary/20 bg-card p-4 shadow-sm sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-xl font-semibold">今日</h2><time className="text-base font-medium tabular-nums" dateTime={today}>{today}</time></header>
      {!hasRecordResult ? record.error ? <p role="alert">今日状态加载失败，暂时无法确认是否已记录。</p> : <p role="status">加载今日状态…</p> : <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1"><p className="font-semibold">{record.data ? "今日已记录" : "今日尚未记录"}</p><p>营业状态：{record.data?.is_open ?? "待记录"}</p></div>
        {record.data && <p className="text-2xl font-semibold tabular-nums sm:text-right">总营业额 {formatWholeEuro(record.data.daily_revenue)}</p>}
      </div>}
      {record.error && hasRecordResult && <p role="alert">今日状态刷新失败，当前显示上次读取的结果。</p>}
      {record.isFetching && hasRecordResult && <p role="status" className="text-sm text-muted-foreground">正在刷新今日状态…</p>}
      <div className="flex flex-wrap gap-2">
        {selected.is_active !== false ? <a className={buttonVariants()} href={`/ledger?date=${today}`}>{record.data ? "修改今日台账" : hasRecordResult ? "立即记账" : "进入记账"}</a> : <p role="status">该门店已归档，仅可查看历史数据和经营分析。</p>}
        {record.error && <Button variant="outline" disabled={record.isFetching} onClick={() => void record.refetch()}>重试今日状态</Button>}
      </div>
    </section>
    <section aria-label="每日简报" className="grid min-w-0 gap-3">
      <header className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-semibold">每日简报</h2>{selected.is_active !== false && <Button variant="outline" disabled={refresh.isPending} onClick={() => refresh.mutate(selected.id)}>刷新简报</Button>}</header>
      {query.isLoading && !query.data ? <p role="status">加载简报…</p> : query.error && !query.data ? <p role="alert">{friendlyApiError(query.error, "简报加载失败，请稍后重试")}</p> : <BriefingCards cards={query.data ?? []} yesterdayHref={selected.is_active !== false ? `/ledger?date=${addDays(today, -1)}` : undefined} />}
      {query.error && query.data && <p role="alert">简报刷新失败，当前显示上次读取的简报。</p>}
      {refresh.error && refresh.variables === selected.id && <p role="alert">{refresh.error instanceof ApiError ? refresh.error.detail : "刷新失败"}</p>}
    </section>
  </section>;
}
