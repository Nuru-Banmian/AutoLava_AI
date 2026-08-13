import { api } from "@/api/client";

export type AgentChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type AgentChatResponse = {
  message: AgentChatMessage;
};

type AgentConversationResponse = {
  messages: AgentChatMessage[];
};

export async function getAgentConversation(storeId: number) {
  return api<AgentConversationResponse>(`/agent/stores/${storeId}/conversation`);
}

export async function sendAgentChatMessage(storeId: number, content: string) {
  return api<AgentChatResponse>(`/agent/stores/${storeId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export async function resetAgentConversation(storeId: number) {
  return api<void>(`/agent/stores/${storeId}/conversation`, { method: "DELETE" });
}
