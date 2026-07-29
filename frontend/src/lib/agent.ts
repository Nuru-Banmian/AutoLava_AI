import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { AgentCurrentStore } from "@/api/types";

export const agentStoreKey = (storeId: number | undefined) => [
  "agent",
  "store",
  storeId,
] as const;

export function useAgentCurrentStore(
  storeId: number | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: agentStoreKey(storeId),
    queryFn: () => api<AgentCurrentStore>(`/agent/stores/${storeId}`),
    enabled: enabled && storeId !== undefined,
    retry: false,
  });
}
