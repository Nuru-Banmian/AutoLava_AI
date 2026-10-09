import { createContext, useContext, useEffect, useMemo } from "react";
import type { ReactNode } from "react";
import { api } from "@/api/client";
import type { components } from "@/api/generated";
import { currentSessionScope, assertSessionScope } from "@/auth/sessionScope";

type Snapshot = components["schemas"]["ChatChart"];

class ChartCache {
  private entries = new Map<string, { promise: Promise<Snapshot>; controller: AbortController }>();
  private epoch = 0;

  read(store: number, message: number, chart: string): Promise<Snapshot> {
    const session = currentSessionScope();
    const key = `${session}:${store}:${message}:${chart}`;
    const cached = this.entries.get(key);
    if (cached) return cached.promise;
    const controller = new AbortController();
    const epoch = this.epoch;
    const promise = api<Snapshot>(`/agent/${store}/messages/${message}/charts/${chart}`, { signal: controller.signal })
      .then(value => {
        assertSessionScope(session);
        if (epoch !== this.epoch || value.chart_id !== chart || value.message_id !== message) {
          throw new Error("图表读取范围已失效");
        }
        return value;
      }).catch(cause => {
        if (this.entries.get(key)?.promise === promise) this.entries.delete(key);
        throw cause;
      });
    this.entries.set(key, { promise, controller });
    return promise;
  }

  clear() {
    this.epoch++;
    for (const entry of this.entries.values()) entry.controller.abort();
    this.entries.clear();
  }
}

const CacheContext = createContext<ChartCache | null>(null);

// The parent keys this provider by authentication/store/conversation/reset epoch.
export function AgentChartCache({ children }: { children: ReactNode }) {
  const cache = useMemo(() => new ChartCache(), []);
  useEffect(() => () => cache.clear(), [cache]);
  return <CacheContext.Provider value={cache}>{children}</CacheContext.Provider>;
}

export function useChartCache() {
  const shared = useContext(CacheContext);
  const local = useMemo(() => new ChartCache(), []);
  useEffect(() => () => local.clear(), [local]);
  return shared ?? local;
}
