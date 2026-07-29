import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { friendlyApiError } from "@/api/client";
import type { AgentInvestigationCard } from "@/api/types";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  AgentStreamEndedError,
  type AgentTurnEvent,
  useAgentConversation,
  useAgentCurrentStore,
  useResetAgentConversation,
  useSendAgentMessage,
} from "@/lib/agent";
import { useStore } from "@/stores/StoreProvider";

function AgentConversationPanel({ storeId }: { storeId: number }) {
  const [draft, setDraft] = useState("");
  const [resetOpen, setResetOpen] = useState(false);
  const [liveAnswer, setLiveAnswer] = useState("");
  const [livePhase, setLivePhase] = useState<string | null>(null);
  const [liveCards, setLiveCards] = useState<AgentInvestigationCard[]>([]);
  const conversation = useAgentConversation(storeId);
  const send = useSendAgentMessage(storeId);
  const reset = useResetAgentConversation(storeId);

  useEffect(() => {
    setDraft("");
    setLiveAnswer("");
    setLivePhase(null);
    setLiveCards([]);
  }, [storeId]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!content) return;
    setLiveAnswer("");
    setLivePhase("正在开始本轮分析…");
    setLiveCards([]);
    send.mutate({
      content,
      onEvent: (streamEvent: AgentTurnEvent) => {
        if (streamEvent.type === "started") {
          setLivePhase("正在查询数据…");
        } else if (streamEvent.type === "phase") {
          setLivePhase({
            querying_data: "正在查询数据…",
            processing_data: "正在处理数据…",
            preparing_answer: "正在准备回答…",
          }[streamEvent.phase]);
        } else if (streamEvent.type === "answer_delta") {
          setLiveAnswer((current) => current + streamEvent.delta);
        } else if (streamEvent.type === "investigation_card") {
          setLivePhase(streamEvent.card.operation);
          setLiveCards((current) => [...current, streamEvent.card]);
        } else if (streamEvent.type === "completed") {
          setLivePhase("回答已完成");
        } else {
          setLivePhase(null);
        }
      },
    }, {
      onSuccess: () => setDraft(""),
    });
  }

  if (conversation.isPending) {
    return <p role="status">正在恢复 Agent 会话…</p>;
  }
  if (conversation.isError) {
    return (
      <p className="text-destructive" role="alert">
        {friendlyApiError(conversation.error, "Agent 会话加载失败，请重试")}
      </p>
    );
  }

  const running = conversation.data.latest_turn?.status === "running";
  const latestAnswer = [...conversation.data.messages]
    .reverse()
    .find((message) => message.role === "assistant")?.content;
  const showLiveAnswer = Boolean(
    liveAnswer && liveAnswer !== latestAnswer && (send.isPending || running),
  );
  const persistedFailure = conversation.data.latest_turn
    && ["failed", "interrupted"].includes(conversation.data.latest_turn.status)
    ? conversation.data.latest_turn.error_message
    : null;
  const investigationCards = liveCards.length > 0
    ? liveCards
    : (conversation.data.latest_turn?.investigation_cards ?? []);

  return (
    <div className="grid gap-4">
      <div
        aria-label="Agent 会话"
        className="grid min-h-48 gap-3 rounded-lg border bg-background p-4"
      >
        {conversation.data.messages.length === 0
          ? (
              <p className="text-sm text-muted-foreground">
                还没有消息，可以从当前门店的经营问题开始。
              </p>
            )
          : conversation.data.messages.map((message) => (
              <article
                className={message.role === "user"
                  ? "ml-auto max-w-[85%] rounded-lg bg-primary px-3 py-2 text-primary-foreground"
                  : "mr-auto max-w-[85%] rounded-lg bg-muted px-3 py-2"}
                key={message.id}
              >
                <p className="mb-1 text-xs font-medium">
                  {message.role === "user" ? "你" : "Agent"}
                </p>
                <p className="whitespace-pre-wrap text-sm">{message.content}</p>
              </article>
            ))}
        {showLiveAnswer && (
          <article className="mr-auto max-w-[85%] rounded-lg bg-muted px-3 py-2">
            <p className="mb-1 text-xs font-medium">Agent</p>
            <p className="whitespace-pre-wrap text-sm">{liveAnswer}</p>
          </article>
        )}
      </div>

      {investigationCards.length > 0 && (
        <section
          aria-label="调查过程"
          className="grid gap-2 rounded-lg border bg-muted/30 p-4"
        >
          <h2 className="text-sm font-semibold">调查过程</h2>
          <ol className="grid gap-2">
            {investigationCards.map((card, index) => (
              <li
                className="rounded-md border bg-background px-3 py-2"
                key={[
                  card.operation,
                  card.range_start,
                  card.range_end,
                  ...card.filters,
                  index,
                ].join("|")}
              >
                <p className="text-sm font-medium">{card.operation}</p>
                {card.range_start && card.range_end && (
                  <p className="text-xs text-muted-foreground">
                    {card.range_start} 至 {card.range_end}
                  </p>
                )}
                {card.filters.length > 0 && (
                  <ul className="mt-1 flex flex-wrap gap-1">
                    {card.filters.map((filter) => (
                      <li
                        className="rounded bg-muted px-2 py-0.5 text-xs"
                        key={filter}
                      >
                        {filter}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}

      {(running || send.isPending) && (
        <p className="text-sm text-muted-foreground" role="status">
          {livePhase ?? "后台处理中，正在恢复结果…"}
        </p>
      )}
      <form className="grid gap-2" onSubmit={submit}>
        <label className="text-sm font-medium" htmlFor="agent-message">
          向 Agent 提问
        </label>
        <textarea
          aria-label="向 Agent 提问"
          className="min-h-24 rounded-md border bg-background px-3 py-2 text-sm"
          id="agent-message"
          maxLength={4000}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="例如：上个月的经营情况怎么样？"
          value={draft}
        />
        {(send.isError || reset.isError || persistedFailure) && (
          <p className="text-sm text-destructive" role="alert">
            {send.error instanceof AgentStreamEndedError
              ? "实时连接已断开，后台仍会继续处理；页面正在恢复结果。"
              : persistedFailure ?? friendlyApiError(
                send.error ?? reset.error,
                send.isError ? "消息发送失败，请重试" : "会话重置失败，请重试",
              )}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={!draft.trim() || send.isPending || running}
            type="submit"
          >
            {send.isPending || running ? "正在回答…" : "发送"}
          </Button>
          <Button
            disabled={reset.isPending}
            onClick={() => setResetOpen(true)}
            type="button"
            variant="outline"
          >
            重置会话
          </Button>
        </div>
      </form>
      <AlertDialog open={resetOpen} onOpenChange={setResetOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认重置 Agent 会话？</AlertDialogTitle>
            <AlertDialogDescription>
              当前门店的 Agent 消息和派生资料会被删除，门店业务记录不会改变。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={reset.isPending}>取消</AlertDialogCancel>
            <Button
              disabled={reset.isPending}
              onClick={() => reset.mutate(undefined, {
                onSuccess: () => {
                  setLiveCards([]);
                  setResetOpen(false);
                },
              })}
              type="button"
              variant="destructive"
            >
              {reset.isPending ? "正在重置…" : "确认重置"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

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
    <section className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">数据分析 Agent</h1>
        <p className="mt-2 text-sm text-muted-foreground">Agent 当前门店</p>
        <p className="text-lg font-medium">{access.data.store_name}</p>
      </div>
      <AgentConversationPanel storeId={access.data.store_id} />
    </section>
  );
}
