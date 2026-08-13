import { api } from "@/api/client";

export type AgentChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type AgentChatResponse = {
  message: AgentChatMessage;
};

export async function sendAgentChatMessage(storeId: number, messages: AgentChatMessage[]) {
  return api<AgentChatResponse>(`/agent/stores/${storeId}/messages`, {
    method: "POST",
    body: JSON.stringify({ messages }),
  });
}
