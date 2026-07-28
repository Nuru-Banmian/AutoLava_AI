import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "@/api/client";
import type { AgentConversation, AgentStatus, AgentTurnResult } from "@/api/types";
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
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { validatedBusinessRecordsAction } from "@/navigation/agent-actions";

const emptyConversation: AgentConversation = {
  id: null,
  messages: [],
  state: {
    confirmed_period: null,
    pending_period: null,
    metrics: [],
    filters: {},
    comparison: null,
    pending_clarifications: [],
  },
  created_at: null,
  updated_at: null,
};

const conversationKey = (storeId: number) => ["agent", "conversation", storeId] as const;

const evidenceSourceLabels = {
  store_daily_records: "每日台账",
  settlement_records: "公司结算",
  open_meteo_historical: "历史天气（外部）",
  nager_date_public_holidays: "公共假期（外部）",
} as const;

function AgentPanelFrame({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section
      aria-labelledby="agent-panel-title"
      className={cn(
        "flex min-h-80 min-w-0 flex-col overflow-hidden rounded-xl border bg-card shadow-sm",
        className,
      )}
    >
      {children}
    </section>
  );
}

function PanelStatus({
  children,
  role = "status",
  className,
}: {
  children: ReactNode;
  role?: "status" | "alert";
  className?: string;
}) {
  return (
    <AgentPanelFrame className={className}>
      <div className="border-b p-4 sm:p-5">
        <h2 className="text-lg font-semibold" id="agent-panel-title">
          门店 Agent
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">当前门店的只读经营调查工作区</p>
      </div>
      <p className="m-auto p-6 text-center text-sm text-muted-foreground" role={role}>
        {children}
      </p>
    </AgentPanelFrame>
  );
}

function currentMonthInTimezone(timezone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}`;
}

export function AgentPanel({
  storeId,
  timezone = "UTC",
  className,
}: {
  storeId: number;
  timezone?: string;
  className?: string;
}) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const [question, setQuestion] = useState("");
  const [turnFeedback, setTurnFeedback] = useState<{
    storeId: number;
    progress: AgentTurnResult["progress"];
    partial: AgentTurnResult["partial"];
    recoveryStatus: AgentTurnResult["recovery_status"];
  } | null>(null);
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
    queryFn: () => api<AgentConversation>(`/agent/stores/${storeId}/conversation`),
  });
  const turn = useMutation({
    mutationFn: async (input: { storeId: number; question: string }) => {
      const result = await api<AgentTurnResult>(`/agent/stores/${input.storeId}/turn`, {
        method: "POST",
        body: JSON.stringify({ question: input.question }),
      });
      setStage({ storeId: input.storeId, value: "organizing" });
      await new Promise((resolve) => window.setTimeout(resolve, 150));
      return { result, storeId: input.storeId };
    },
    onMutate: (input) => {
      setTurnFeedback(null);
      setStage({ storeId: input.storeId, value: "understanding" });
      setPendingQuestion({ storeId: input.storeId, content: input.question });
      setQuestion("");
    },
    onSuccess: ({ result, storeId: requestedStoreId }) => {
      client.setQueryData(conversationKey(requestedStoreId), result.conversation);
      setTurnFeedback({
        storeId: requestedStoreId,
        progress: result.progress ?? [],
        partial: result.partial ?? null,
        recoveryStatus: result.recovery_status ?? "none",
      });
      setPendingQuestion(null);
      setStage(null);
      window.setTimeout(() => questionRef.current?.focus(), 0);
    },
    onError: async (_error, input) => {
      setPendingQuestion(null);
      setStage(null);
      setTurnFeedback(null);
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
      setTurnFeedback(null);
      turn.reset();
      window.setTimeout(() => questionRef.current?.focus(), 0);
    },
  });

  function sendQuestion(input: string) {
    const value = input.trim();
    if (!value || turn.isPending) return;
    turn.mutate({ storeId, question: value });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    sendQuestion(question);
  }

  if (status.isPending)
    return <PanelStatus className={className}>正在检查 Agent 状态…</PanelStatus>;
  if (status.isError) {
    return (
      <PanelStatus className={className} role="alert">
        Agent 状态暂时无法获取
      </PanelStatus>
    );
  }
  if (!status.data.enabled) {
    return <PanelStatus className={className}>Agent 当前未启用</PanelStatus>;
  }
  if (currentConversation.isPending) {
    return <PanelStatus className={className}>正在恢复当前调查…</PanelStatus>;
  }
  if (currentConversation.isError) {
    return (
      <PanelStatus className={className} role="alert">
        当前调查暂时无法恢复
      </PanelStatus>
    );
  }

  const messages = currentConversation.data.messages;
  const state = currentConversation.data.state;
  const evidence = state.evidence_references ?? [];
  const hypotheses = state.analysis_hypotheses ?? [];
  const pendingDirections = state.pending_directions ?? [];
  const mutationError = turn.error ?? reset.error;
  const visiblePendingQuestion =
    pendingQuestion?.storeId === storeId ? pendingQuestion.content : null;
  const visibleStage = stage?.storeId === storeId ? stage.value : null;
  const visibleTurnFeedback = turnFeedback?.storeId === storeId ? turnFeedback : null;
  const visibleProgress = visibleTurnFeedback?.progress ?? [];
  const visiblePartial = visibleTurnFeedback?.partial ?? null;
  const visibleRecoveryStatus = visibleTurnFeedback?.recoveryStatus ?? "none";

  return (
    <AgentPanelFrame className={className}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b p-4 sm:p-5">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold" id="agent-panel-title">
            门店 Agent
          </h2>
          <p className="text-sm text-muted-foreground">当前门店的只读经营调查工作区</p>
          {state.investigation_goal && (
            <p className="max-w-2xl text-sm">
              <span className="font-medium">当前目标：</span>
              {state.investigation_goal}
            </p>
          )}
        </div>
        {messages.length > 0 && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button disabled={turn.isPending || reset.isPending} variant="outline">
                开始新调查
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>永久删除当前调查？</AlertDialogTitle>
                <AlertDialogDescription>
                  此操作不可恢复。当前门店的全部消息、回答、工具证据、证据引用、分析假设和结构化调查上下文都会永久删除，不会保留历史调查。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>取消</AlertDialogCancel>
                <AlertDialogAction onClick={() => reset.mutate(storeId)}>
                  永久删除并开始新调查
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 sm:p-5">
        {state.pending_period && (
          <section
            aria-label="待确认期间"
            className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950"
          >
            <h3 className="font-medium">请确认推定期间</h3>
            <p className="mt-1 text-sm">
              {state.pending_period.start} 至 {state.pending_period.end}
            </p>
            <p className="mt-1 text-sm">确认前不会查询正式经营证据。</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                disabled={turn.isPending}
                onClick={() => sendQuestion("确认")}
                size="sm"
                type="button"
              >
                确认这个期间
              </Button>
              <Button
                disabled={turn.isPending}
                onClick={() => {
                  setQuestion("请改为 ");
                  window.setTimeout(() => questionRef.current?.focus(), 0);
                }}
                size="sm"
                type="button"
                variant="outline"
              >
                修改期间
              </Button>
            </div>
          </section>
        )}

        {messages.length === 0 && visiblePendingQuestion === null ? (
          <div className="grid min-h-48 place-items-center rounded-lg border border-dashed p-6 text-center">
            <div>
              <p className="font-medium">当前调查为空</p>
              <p className="mt-1 text-sm text-muted-foreground">
                可以询问当前门店的经营表现、异常日期或数据依据。
              </p>
            </div>
          </div>
        ) : (
          <ol className="space-y-3" aria-label="当前调查">
            {messages.map((message) => {
              const action = validatedBusinessRecordsAction(
                message.action,
                currentMonthInTimezone(timezone),
              );
              return (
                <li
                  className={cn(
                    "min-w-0 break-words rounded-xl p-4 text-sm leading-6",
                    message.role === "user"
                      ? "ml-auto max-w-[85%] bg-primary text-primary-foreground"
                      : "mr-auto max-w-[92%] border bg-background",
                  )}
                  key={message.id}
                >
                  <p className="mb-1 text-xs font-medium opacity-75">
                    {message.role === "user" ? "你" : "Agent"}
                  </p>
                  <p className="whitespace-pre-wrap">{message.content}</p>
                  {message.role === "assistant" && action && (
                    <div className="mt-3">
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          navigate("/database", {
                            state: { agentBusinessRecordsAction: action },
                          })
                        }
                      >
                        查看营业记录
                      </Button>
                    </div>
                  )}
                </li>
              );
            })}
            {visiblePendingQuestion !== null && (
              <li className="ml-auto max-w-[85%] min-w-0 break-words rounded-xl bg-primary p-4 text-sm text-primary-foreground">
                <p className="mb-1 text-xs font-medium opacity-75">你</p>
                <p className="whitespace-pre-wrap">{visiblePendingQuestion}</p>
              </li>
            )}
          </ol>
        )}

        {(visibleStage ||
          visibleProgress.length > 0 ||
          pendingDirections.length > 0 ||
          visibleRecoveryStatus !== "none") && (
          <section
            aria-label="调查进度"
            aria-live="polite"
            className="rounded-lg bg-muted/60 p-3 text-sm"
            role="status"
          >
            <h3 className="font-medium">调查进度</h3>
            {visibleStage ? (
              <p className="mt-1 text-muted-foreground">
                {visibleStage === "understanding" ? "正在理解问题…" : "正在整理回答…"}
              </p>
            ) : (
              <ul className="mt-1 space-y-1 text-muted-foreground">
                {visibleProgress.map((item, index) => (
                  <li key={`${item.status}-${index}`}>{item.message}</li>
                ))}
                {pendingDirections.map((direction) => (
                  <li key={direction}>待继续：{direction}</li>
                ))}
                {visibleRecoveryStatus === "retried" && <li>部分取证曾暂时失败，已自动重试。</li>}
                {visibleRecoveryStatus === "fallback" && (
                  <li>主要调查路径暂时不可用，已返回安全降级结果。</li>
                )}
              </ul>
            )}
          </section>
        )}

        {visiblePartial && (
          <section
            aria-label="部分调查结果"
            className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950"
          >
            <h3 className="font-medium">部分调查结果</h3>
            {visiblePartial.verified_facts.length > 0 && (
              <>
                <h4 className="mt-3 text-sm font-medium">已验证</h4>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                  {visiblePartial.verified_facts.map((fact) => (
                    <li key={fact}>{fact}</li>
                  ))}
                </ul>
              </>
            )}
            <h4 className="mt-3 text-sm font-medium">仍待核对</h4>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
              {visiblePartial.incomplete_directions.map((direction) => (
                <li key={direction}>尚未完成：{direction}</li>
              ))}
              {visiblePartial.unknowns.map((unknown) => (
                <li key={unknown}>{unknown}</li>
              ))}
            </ul>
          </section>
        )}

        {hypotheses.length > 0 && (
          <section aria-label="分析假设" className="rounded-lg border p-4">
            <h3 className="font-medium">分析假设</h3>
            <ul className="mt-2 space-y-2 text-sm">
              {hypotheses.map((hypothesis) => (
                <li key={`${hypothesis.status}-${hypothesis.statement}`}>
                  {hypothesis.statement}
                  <span className="ml-2 text-muted-foreground">
                    {hypothesis.status === "supported"
                      ? "已支持"
                      : hypothesis.status === "refuted"
                        ? "已排除"
                        : "仍待检验"}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {evidence.length > 0 && (
          <div aria-label="调查证据" className="space-y-2" role="group">
            <h3 className="font-medium">调查证据</h3>
            {evidence.map((item) => {
              const external = item.source.some(
                (source) => source.includes("historical") || source.includes("holidays"),
              );
              return (
                <details className="rounded-lg border bg-background p-3" key={item.reference}>
                  <summary className="cursor-pointer font-medium">
                    {external ? "外部经营证据" : "经营数据"} · {item.period.start} 至{" "}
                    {item.period.end}
                  </summary>
                  <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-[5rem_1fr]">
                    <dt className="text-muted-foreground">来源</dt>
                    <dd>{item.source.map((source) => evidenceSourceLabels[source]).join("、")}</dd>
                    <dt className="text-muted-foreground">证据范围</dt>
                    <dd>
                      {item.period.start} 至 {item.period.end}
                    </dd>
                    <dt className="text-muted-foreground">查询时间</dt>
                    <dd>
                      {new Date(item.queried_at).toLocaleString("zh-CN", { timeZone: timezone })}
                    </dd>
                  </dl>
                  <p className="mt-3 text-xs text-muted-foreground">
                    该证据用于核对本轮回答；后续需要新事实时会重新取证。
                  </p>
                </details>
              );
            })}
          </div>
        )}
      </div>

      <form className="grid min-w-0 gap-3 border-t bg-card p-4 sm:p-5" onSubmit={submit}>
        <label className="text-sm font-medium" htmlFor="agent-question">
          向 Agent 提问
        </label>
        <textarea
          className="min-h-24 w-full min-w-0 resize-y rounded-md border bg-background px-3 py-2 text-base sm:text-sm"
          disabled={turn.isPending || reset.isPending}
          id="agent-question"
          maxLength={2000}
          onChange={(event) => setQuestion(event.target.value)}
          ref={questionRef}
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
    </AgentPanelFrame>
  );
}
