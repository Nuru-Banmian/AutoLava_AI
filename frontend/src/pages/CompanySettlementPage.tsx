import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api, friendlyApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { useStore } from "@/stores/StoreProvider";

interface SettlementWorkspace {
  store_id: number;
  store_name: string;
  company_settlement_enabled: true;
}

export function CompanySettlementPage() {
  const { selected, isLoading } = useStore();
  const enabled = selected?.company_settlement_enabled === true;
  const workspace = useQuery({
    queryKey: ["settlements", selected?.id],
    queryFn: () => api<SettlementWorkspace>(`/settlements/${selected!.id}`),
    enabled: Boolean(selected && enabled),
  });

  if (isLoading) return <p role="status">正在加载门店…</p>;
  if (!selected) return <p role="alert">没有可访问的门店。</p>;
  if (!enabled) {
    return <section className="space-y-3" aria-labelledby="settlement-title">
      <h1 id="settlement-title" className="text-2xl font-semibold">公司结算</h1>
      <p role="alert">当前门店未启用公司结算。</p>
      <Link className="text-primary underline" to="/">返回首页</Link>
    </section>;
  }
  if (workspace.error) return <div className="space-y-3" role="alert">
    <p>{friendlyApiError(workspace.error, "公司结算加载失败")}</p>
    <Button onClick={() => void workspace.refetch()} type="button" variant="outline">重试公司结算</Button>
  </div>;

  return <section className="space-y-2" aria-labelledby="settlement-title">
    <h1 id="settlement-title" className="text-2xl font-semibold">公司结算</h1>
    <p className="text-sm text-muted-foreground">
      {workspace.data ? `${workspace.data.store_name}的公司结算` : "正在加载公司结算…"}
    </p>
  </section>;
}
