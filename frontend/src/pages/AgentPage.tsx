import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";

import { AgentPanel } from "@/components/AgentPanel";
import { useStore } from "@/stores/StoreProvider";

export function AgentPage() {
  const { selected } = useStore();

  if (!selected) {
    return (
      <section className="grid h-full place-items-center p-4">
        <p role="status">请先选择门店。</p>
      </section>
    );
  }

  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col bg-background pb-[env(safe-area-inset-bottom)]">
      <header className="flex shrink-0 items-center gap-3 border-b px-4 py-3 md:mb-4 md:border-0 md:p-0">
        <Link
          aria-label="返回首页"
          className="inline-flex size-10 items-center justify-center rounded-md hover:bg-accent md:hidden"
          to="/"
        >
          <ArrowLeft aria-hidden="true" className="size-5" />
        </Link>
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold md:text-2xl">当前调查</h1>
          <p className="truncate text-xs text-muted-foreground md:hidden">{selected.name}</p>
        </div>
      </header>
      <AgentPanel
        key={selected.id}
        className="h-full min-h-0 flex-1 rounded-none border-0 shadow-none md:rounded-xl md:border md:shadow-sm"
        storeId={selected.id}
        timezone={selected.timezone}
      />
    </section>
  );
}
