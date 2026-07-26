import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, ApiError } from "@/api/client";
import type {
  AgentConversation,
  AgentStatus,
  AgentTurnResult,
} from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

const emptyConversation: AgentConversation = {
  id: null,
  messages: [],
  state: {
    confirmed_period: null,
    metrics: [],
    filters: {},
    comparison: null,
    pending_clarifications: [],
  },
  created_at: null,
  updated_at: null,
};

const conversationKey = (storeId: number) =>
  ["agent", "conversation", storeId] as const;

export function AgentPanel({ storeId }: { storeId: number }) {
  const client = useQueryClient();
  const [question, setQuestion] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState<{
    storeId: number;
    content: string;
  } | null>(null);
  const [stage, setStage] = useState<{
    storeId: number;
    value: "understanding" | "organizing";
  } | null>(null);
  const status = useQuery({
    queryKey: ["agent", "status"],
    queryFn: () => api<AgentStatus>("/agent/status"),
  });
  const currentConversation = useQuery({
    queryKey: conversationKey(storeId),
    enabled: status.data?.enabled === true,
    queryFn: () =>
      api<AgentConversation>(`/agent/stores/${storeId}/conversation`),
  });
  const turn = useMutation({
    mutationFn: async (input: { storeId: number; question: string }) => {
      const result = await api<AgentTurnResult>(
        `/agent/stores/${input.storeId}/turn`,
        {
          method: "POST",
          body: JSON.stringify({ question: input.question }),
        },
      );
      setStage({ storeId: input.storeId, value: "organizing" });
      await new Promise((resolve) => window.setTimeout(resolve, 150));
      return { result, storeId: input.storeId };
    },
    onMutate: (input) => {
      setStage({ storeId: input.storeId, value: "understanding" });
      setPendingQuestion({ storeId: input.storeId, content: input.question });
      setQuestion("");
    },
    onSuccess: ({ result, storeId: requestedStoreId }) => {
      client.setQueryData(
        conversationKey(requestedStoreId),
        result.conversation,
      );
      setPendingQuestion(null);
      setStage(null);
    },
    onError: async (_error, input) => {
      setPendingQuestion(null);
      setStage(null);
      await client.invalidateQueries({
        queryKey: conversationKey(input.storeId),
        exact: true,
      });
    },
  });
  const reset = useMutation({
    mutationFn: async (requestedStoreId: number) => {
      await api<void>(`/agent/stores/${requestedStoreId}/conversation`, {
        method: "DELETE",
        body: JSON.stringify({ confirmation: "permanently_delete" }),
      });
      return requestedStoreId;
    },
    onSuccess: (resetStoreId) => {
      client.setQueryData(conversationKey(resetStoreId), emptyConversation);
      setPendingQuestion(null);
      setQuestion("");
      setStage(null);
      turn.reset();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const input = question.trim();
    if (!input || turn.isPending) return;
    turn.mutate({ storeId, question: input });
  }

  if (status.isPending) return <p role="status">正在检查 Agent 状态…</p>;
  if (status.isError) {
    return <p role="alert">Agent 状态暂时无法获取</p>;
  }
  if (!status.data.enabled) {
    return <p className="text-sm text-muted-foreground">Agent 当前未启用</p>;
  }
  if (currentConversation.isPending) {
    return <p role="status">正在恢复当前对话…</p>;
  }
  if (currentConversation.isError) {
    return <p role="alert">当前对话暂时无法恢复</p>;
  }

  const messages = currentConversation.data.messages;
  const mutationError = turn.error ?? reset.error;
  const visiblePendingQuestion =
    pendingQuestion?.storeId === storeId ? pendingQuestion.content : null;
  const visibleStage = stage?.storeId === storeId ? stage.value : null;

  return (
    <section
      aria-labelledby="agent-panel-title"
      className="min-w-0 overflow-hidden rounded-xl border bg-card p-4 shadow-sm sm:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="font-medium" id="agent-panel-title">门店 Agent</h2>
          <p className="text-sm text-muted-foreground">
            针对当前门店提问；需要经营证据的查询将在后续切片开放。
          </p>
        </div>
        {messages.length > 0 && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button disabled={turn.isPending || reset.isPending} variant="outline">
                重置对话
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>永久重置当前对话？</AlertDialogTitle>
                <AlertDialogDescription>
                  此操作不可恢复。当前门店的全部消息、结构化状态和关联经营证据都会永久删除。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>取消</AlertDialogCancel>
                <AlertDialogAction onClick={() => reset.mutate(storeId)}>
                  确认永久重置
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
      {messages.length === 0 && visiblePendingQuestion === null ? (
        <p className="mt-4 text-sm text-muted-foreground">当前对话为空</p>
      ) : (
        <ol className="mt-4 space-y-3" aria-label="当前对话">
          {messages.map((message) => (
            <li
              className="min-w-0 break-words rounded-lg bg-muted/50 p-3 text-sm"
              key={message.id}
            >
              <span className="font-medium">
                {message.role === "user" ? "你" : "Agent"}：
              </span>
              {message.content}
            </li>
          ))}
          {visiblePendingQuestion !== null && (
            <li className="min-w-0 break-words rounded-lg bg-muted/50 p-3 text-sm">
              <span className="font-medium">你：</span>
              {visiblePendingQuestion}
            </li>
          )}
        </ol>
      )}
      {visibleStage && (
        <p className="mt-3 text-sm text-muted-foreground" role="status">
          {visibleStage === "understanding" ? "正在理解问题…" : "正在整理回答…"}
        </p>
      )}
      <form className="mt-4 grid min-w-0 gap-3" onSubmit={submit}>
        <label className="text-sm font-medium" htmlFor="agent-question">
          向 Agent 提问
        </label>
        <textarea
          className="min-h-24 w-full min-w-0 resize-y rounded-md border bg-background px-3 py-2 text-base sm:text-sm"
          disabled={turn.isPending || reset.isPending}
          id="agent-question"
          maxLength={2000}
          onChange={(event) => setQuestion(event.target.value)}
          value={question}
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={turn.isPending || reset.isPending || !question.trim()} type="submit">
            发送问题
          </Button>
          {mutationError && (
            <p className="text-sm text-destructive" role="alert">
              {mutationError instanceof ApiError
                ? mutationError.detail
                : "Agent 暂时不可用，请稍后重试"}
            </p>
          )}
        </div>
      </form>
    </section>
  );
}
