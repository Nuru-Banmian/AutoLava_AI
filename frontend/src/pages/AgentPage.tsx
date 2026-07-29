import { Link } from "react-router-dom";

import { friendlyApiError } from "@/api/client";
import { useAgentCurrentStore } from "@/lib/agent";
import { useStore } from "@/stores/StoreProvider";

export function AgentPage() {
  const { selected } = useStore();
  const access = useAgentCurrentStore(selected?.id);

  if (!selected) {
    return (
      <section>
        <h1 className="text-2xl font-semibold">数据分析 Agent</h1>
        <p role="status">请先选择门店。</p>
      </section>
    );
  }
  if (access.isPending) {
    return <p role="status">正在进入 Agent 当前门店…</p>;
  }
  if (access.isError) {
    return (
      <section className="space-y-3">
        <h1 className="text-2xl font-semibold">数据分析 Agent</h1>
        <p className="text-destructive" role="alert">
          {friendlyApiError(access.error, "当前无法进入数据分析 Agent")}
        </p>
        <Link className="text-sm text-primary underline" to="/">返回首页</Link>
      </section>
    );
  }

  return (
    <section className="space-y-3">
      <h1 className="text-2xl font-semibold">数据分析 Agent</h1>
      <p className="text-sm text-muted-foreground">Agent 当前门店</p>
      <p className="text-lg font-medium">{access.data.store_name}</p>
      <p className="text-sm text-muted-foreground">
        分析对话能力将在后续纵向切片中交付。
      </p>
    </section>
  );
}
