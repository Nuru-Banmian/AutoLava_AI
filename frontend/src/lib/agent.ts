import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, apiRequest } from "@/api/client";
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

export type AgentTurnEvent =
  | { type: "started"; turn_id: number }
  | {
      type: "phase";
      turn_id: number;
      phase: "querying_data" | "processing_data" | "preparing_answer";
    }
  | {
      type: "investigation_card";
      turn_id: number;
      card: {
        operation: string;
        actual_scope: string;
        filters: string[];
        status: "running" | "completed" | "failed";
      };
    }
  | { type: "answer_delta"; turn_id: number; delta: string }
  | { type: "completed"; turn_id: number; partial?: boolean }
  | { type: "failed"; turn_id: number; message: string };

export class AgentStreamEndedError extends Error {
  constructor() {
    super("Agent stream ended before a terminal event");
    this.name = "AgentStreamEndedError";
  }
}

async function streamAgentMessage(
  storeId: number,
  content: string,
  onEvent: (event: AgentTurnEvent) => void,
) {
  const response = await apiRequest(`/agent/stores/${storeId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
  if (!response.body) throw new AgentStreamEndedError();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminalEvent: Extract<
    AgentTurnEvent,
    { type: "completed" | "failed" }
  > | null = null;

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : (lines.pop() ?? "");
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as AgentTurnEvent;
      onEvent(event);
      if (event.type === "completed" || event.type === "failed") {
        terminalEvent = event;
      }
    }
    if (done) break;
  }

  if (terminalEvent?.type === "failed") {
    throw new ApiError(500, terminalEvent.message);
  }
  if (terminalEvent?.type !== "completed") {
    throw new AgentStreamEndedError();
  }
}

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
    refetchInterval: (query) => (
      query.state.data?.latest_turn?.status === "running" ? 1000 : false
    ),
  });
}

export function useSendAgentMessage(storeId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      content,
      onEvent,
    }: {
      content: string;
      onEvent: (event: AgentTurnEvent) => void;
    }) => streamAgentMessage(storeId, content, onEvent),
    onSettled: () => queryClient.invalidateQueries({
      queryKey: agentConversationKey(storeId),
    }),
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
          ? { ...conversation, messages: [], latest_turn: null }
          : conversation,
      );
    },
  });
}
