import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api, ApiError } from "@/api/client";
import type { AgentStatus, AgentTurnResult } from "@/api/types";
import { Button } from "@/components/ui/button";

type ConversationEntry = {
  id: number;
  role: "user" | "agent";
  content: string;
};

export function AgentPanel({ storeId }: { storeId: number }) {
  const [question, setQuestion] = useState("");
  const [entries, setEntries] = useState<ConversationEntry[]>([]);
  const [stage, setStage] = useState<"understanding" | "organizing" | null>(
    null,
  );
  const status = useQuery({
    queryKey: ["agent", "status"],
    queryFn: () => api<AgentStatus>("/agent/status"),
  });
  const turn = useMutation({
    mutationFn: async (input: string) => {
      const result = await api<AgentTurnResult>(`/agent/stores/${storeId}/turn`, {
        method: "POST",
        body: JSON.stringify({ question: input }),
      });
      setStage("organizing");
      await new Promise((resolve) => window.setTimeout(resolve, 150));
      return result;
    },
    onMutate: (input) => {
      setStage("understanding");
      setEntries((current) => [
        ...current,
        { id: Date.now(), role: "user", content: input },
      ]);
      setQuestion("");
    },
    onSuccess: (result) => {
      setEntries((current) => [
        ...current,
        { id: Date.now() + 1, role: "agent", content: result.content },
      ]);
      setStage(null);
    },
    onError: () => setStage(null),
  });

  useEffect(() => {
    turn.reset();
    setEntries([]);
    setQuestion("");
    setStage(null);
  }, [storeId]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const input = question.trim();
    if (!input || turn.isPending) return;
    turn.mutate(input);
  }

  if (status.isPending) return <p role="status">正在检查 Agent 状态…</p>;
  if (status.isError) {
    return <p role="alert">Agent 状态暂时无法获取</p>;
  }
  if (!status.data.enabled) {
    return <p className="text-sm text-muted-foreground">Agent 当前未启用</p>;
  }

  return (
    <section
      aria-labelledby="agent-panel-title"
      className="min-w-0 overflow-hidden rounded-xl border bg-card p-4 shadow-sm sm:p-5"
    >
      <div className="space-y-1">
        <h2 className="font-medium" id="agent-panel-title">门店 Agent</h2>
        <p className="text-sm text-muted-foreground">
          针对当前门店提问；需要经营证据的查询将在后续切片开放。
        </p>
      </div>
      {entries.length > 0 && (
        <ol className="mt-4 space-y-3" aria-label="当前对话">
          {entries.map((entry) => (
            <li
              className="min-w-0 break-words rounded-lg bg-muted/50 p-3 text-sm"
              key={entry.id}
            >
              <span className="font-medium">
                {entry.role === "user" ? "你" : "Agent"}：
              </span>
              {entry.content}
            </li>
          ))}
        </ol>
      )}
      {stage && (
        <p className="mt-3 text-sm text-muted-foreground" role="status">
          {stage === "understanding" ? "正在理解问题…" : "正在整理回答…"}
        </p>
      )}
      <form className="mt-4 grid min-w-0 gap-3" onSubmit={submit}>
        <label className="text-sm font-medium" htmlFor="agent-question">
          向 Agent 提问
        </label>
        <textarea
          className="min-h-24 w-full min-w-0 resize-y rounded-md border bg-background px-3 py-2 text-base sm:text-sm"
          disabled={turn.isPending}
          id="agent-question"
          maxLength={2000}
          onChange={(event) => setQuestion(event.target.value)}
          value={question}
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={turn.isPending || !question.trim()} type="submit">
            发送问题
          </Button>
          {turn.error && (
            <p className="text-sm text-destructive" role="alert">
              {turn.error instanceof ApiError
                ? turn.error.detail
                : "Agent 暂时不可用，请稍后重试"}
            </p>
          )}
        </div>
      </form>
    </section>
  );
}
