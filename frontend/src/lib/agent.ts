import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { AgentConversation, AgentCurrentStore } from "@/api/types";

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

export const agentConversationKey = (storeId: number | undefined) => [
  "agent",
  "conversation",
  storeId,
] as const;

export function useAgentConversation(
  storeId: number | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: agentConversationKey(storeId),
    queryFn: () => api<AgentConversation>(
      `/agent/stores/${storeId}/conversation`,
    ),
    enabled: enabled && storeId !== undefined,
    retry: false,
  });
}

export function useSendAgentMessage(storeId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (content: string) => api<AgentConversation>(
      `/agent/stores/${storeId}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ content }),
      },
    ),
    onSuccess: (conversation) => {
      queryClient.setQueryData(agentConversationKey(storeId), conversation);
    },
  });
}

export function useResetAgentConversation(storeId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>(
      `/agent/stores/${storeId}/conversation`,
      { method: "DELETE" },
    ),
    onSuccess: () => {
      queryClient.setQueryData<AgentConversation>(
        agentConversationKey(storeId),
        (conversation) => conversation
          ? { ...conversation, messages: [] }
          : conversation,
      );
    },
  });
}
