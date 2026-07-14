import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api, ApiError } from "@/api/client";
import type { BriefingCard } from "@/api/types";
import { BriefingCards } from "@/components/BriefingCards";
import { Button } from "@/components/ui/button";
import { dashboardKey } from "@/lib/user-api";
import { useStore } from "@/stores/StoreProvider";
export function HomePage() {
  const { selected } = useStore(); const client = useQueryClient();
  const query = useQuery({ queryKey: selected ? dashboardKey(selected.id) : ["dashboard", "none"], enabled: Boolean(selected), queryFn: () => api<BriefingCard[]>(`/dashboard/${selected!.id}`) });
  const refresh = useMutation({ mutationFn: (storeId: number) => api<BriefingCard[]>(`/dashboard/${storeId}/refresh`, { method: "POST" }), onSuccess: async (cards, storeId) => { client.setQueryData(dashboardKey(storeId), cards); await client.invalidateQueries({ queryKey: dashboardKey(storeId), exact: true }); } });
  useEffect(() => refresh.reset(), [selected?.id]);
  if (!selected) return <section><h1 className="text-2xl font-semibold">仪表盘</h1><p role="status">请先选择门店。</p></section>;
  return <section className="grid gap-4"><header className="flex items-center justify-between"><h1 className="text-2xl font-semibold">仪表盘</h1><Button disabled={refresh.isPending} onClick={() => refresh.mutate(selected.id)}>刷新简报</Button></header>
    {query.isLoading && !query.data ? <p role="status">加载简报…</p> : query.error && !query.data ? <p role="alert">{query.error.message}</p> : <BriefingCards cards={query.data ?? []} />}
    {refresh.error && refresh.variables === selected.id && <p role="alert">{refresh.error instanceof ApiError ? refresh.error.detail : "刷新失败"}</p>}
  </section>;
}
