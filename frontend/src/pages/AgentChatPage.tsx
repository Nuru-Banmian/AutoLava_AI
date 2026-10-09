import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { ArrowDown, ArrowUp, Bot, MessageSquare, RotateCcw, Square, UserRound } from "lucide-react";

import { api, friendlyApiError } from "@/api/client";
import type { components } from "@/api/generated";
import { useAuth } from "@/auth/AuthProvider";
import { currentSessionScope } from "@/auth/sessionScope";
import { AgentMarkdown } from "@/components/AgentMarkdown";
import { AgentChart } from "@/components/AgentChart";
import { AgentChartCache } from "@/components/AgentChartCache";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useStore } from "@/stores/StoreProvider";
import { AgentMemoryPanel } from "./AgentMemoryPanel";
import { ChatExamplePreview, ChatExamples, ChatQuestionButtons } from "./AgentChatGuide";

type Conversation = components["schemas"]["ChatConversation"];
type Run = components["schemas"]["ChatRun"];

const failures: Record<string, string> = {
  model_not_configured: "聊天模型尚未配置，请联系管理员。",
  model_configuration: "模型配置或访问权限有误，请联系管理员。",
  model_timeout: "模型响应超时，请稍后重新发送。",
  model_rate_limited: "模型请求过于频繁，请稍后重新发送。",
  model_unavailable: "模型服务暂时不可用，请稍后重新发送。",
  model_format: "模型返回的内容不完整或格式不受支持。",
  grounding_plan: "本轮未能确定可靠的查询计划，请明确问题和日期范围后重新发送。",
  grounding_unavailable: "本轮未取得所需经营数据，请检查查询范围后重试。",
  output_budget: "回答达到输出上限，请缩小问题范围。",
  access_revoked: "当前会话或门店权限已失效。",
  interrupted: "本次回答已中断。",
  cancelled: "本次回答已停止。",
  reset: "对话已重置。",
  step_budget: "已达到本轮处理次数上限，请缩小问题范围。",
  tool_budget: "已达到本轮工具次数上限，请缩小问题范围。",
  context_budget: "本轮资料超过上下文上限，请缩小查询范围或重置对话。",
  memory_invalid_proposal: "记忆提议未通过校验，未确认保存成功，请重新明确表达。",
  memory_version_conflict: "门店背景或记忆已更新，本次未保存，请重新发送。",
  memory_context_budget: "记忆资料超过处理上限，本次未保存。",
  memory_output_budget: "记忆模型输出超过上限，本次未保存。",
  memory_model_not_configured: "记忆模型尚未配置，本次未保存，请联系管理员。",
  memory_model_configuration: "记忆模型配置或访问权限有误，本次未保存。",
  memory_model_timeout: "记忆处理超时，请查看记忆确认保存状态后重试。",
  memory_model_unavailable: "记忆模型暂时不可用，本次未保存。",
  memory_model_rate_limited: "记忆模型请求过于频繁，本次未保存。",
  memory_model_format: "记忆模型返回格式有误，本次未保存。",
};

function ChatMessage({ role = "assistant", content, children }: { role?: string; content: string; children?: ReactNode }) {
  const user = role === "user";
  return <article aria-label={user ? "你的消息" : "AI 助手的消息"} className={`flex min-w-0 items-start gap-2.5 sm:gap-3 ${user ? "flex-row-reverse" : ""}`}>
    <div aria-hidden="true" className={`grid size-8 shrink-0 place-items-center rounded-xl sm:size-9 ${user ? "bg-primary/10 text-primary" : "bg-primary text-primary-foreground"}`}>
      {user ? <UserRound className="size-4" /> : <Bot className="size-5" />}
    </div>
    <div className={`min-w-0 max-w-[calc(100%-2.75rem)] sm:max-w-[85%] ${user ? "text-right" : ""}`}>
      <p className="mb-1.5 text-xs font-medium text-muted-foreground">{user ? "你" : "AI 助手"}</p>
      <div className={`min-w-0 rounded-2xl px-3.5 py-3 text-left text-sm sm:px-4 sm:text-[15px] ${user ? "rounded-tr-sm bg-primary text-primary-foreground" : "rounded-tl-sm border bg-card shadow-sm"}`}>
        {user ? <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{content}</p> : <AgentMarkdown content={content} />}
        {children}
      </div>
    </div>
  </article>;
}

function Chat({ storeId }: { storeId: number }) {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState("");
  const [exampleIndex, setExampleIndex] = useState<number | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("");
  const [activity, setActivity] = useState<{ runId: string; text: string } | null>(null);
  const [retrieval, setRetrieval] = useState<{ runId: string; text: string } | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const transcript = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const followLatest = useRef(true);
  const olderScroll = useRef<{ height: number; top: number } | null>(null);
  const epoch = useRef(0);
  const reads = useRef(0);
  const pending = useRef<{ content: string; request_id: string; generation: number } | null>(null);
  const alive = useRef(false);
  const generation = useRef(currentSessionScope());
  const valid = (version = epoch.current) => alive.current && generation.current === currentSessionScope() && version === epoch.current;
  const base = `/agent/${storeId}`;

  async function reload() {
    const version = epoch.current;
    const read = ++reads.current;
    try {
      const value = await api<Conversation>(`${base}/conversation`);
      if (valid(version) && read === reads.current) {
        if (value.run?.request_id === pending.current?.request_id) pending.current = null;
        setConversation(value); setError("");
      }
    } catch (cause) {
      if (valid(version) && read === reads.current) setError(friendlyApiError(cause, "对话加载失败，请重试"));
    }
  }

  useEffect(() => {
    alive.current = true;
    void reload();
    return () => { alive.current = false; epoch.current++; };
    // Each store/session has its own keyed component and event lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runId = conversation?.run?.id;
  const status = conversation?.run?.status;
  useLayoutEffect(() => {
    const input = composer.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(144, Math.max(64, input.scrollHeight))}px`;
  }, [draft]);
  useLayoutEffect(() => {
    const element = transcript.current;
    if (!element) return;
    if (olderScroll.current) {
      element.scrollTop = olderScroll.current.top + element.scrollHeight - olderScroll.current.height;
      olderScroll.current = null;
    } else if (followLatest.current) {
      element.scrollTop = element.scrollHeight;
    }
  }, [conversation?.messages, conversation?.run?.output, status]);
  useEffect(() => {
    if (!runId || status !== "running" || controlling) return;
    const version = epoch.current;
    const source = new EventSource(`/api${base}/runs/${runId}/events`, { withCredentials: true });
    let output = "";
    let disposed = false;
    let lastEventId = 0;
    const current = () => !disposed && valid(version);
    source.onopen = () => { if (current()) setConnection(""); };
    source.addEventListener("retrieval", (event) => {
      if (!current()) return;
      const data = JSON.parse((event as MessageEvent).data) as {
        status: string; references: { id: string; version: number }[];
      };
      setRetrieval({ runId, text: data.status === "available"
        ? (data.references.length ? `本轮参考记忆：${data.references.map((m) => `${m.id}（版本 ${m.version}）`).join("、")}` : "本轮未检索到相关记忆")
        : "记忆检索受限，本轮未参考长期记忆" });
    });
    source.addEventListener("tool", (event) => {
      if (!current()) return;
      const id = Number((event as MessageEvent).lastEventId);
      if (id && id <= lastEventId) return;
      if (id) lastEventId = id;
      const data = JSON.parse((event as MessageEvent).data) as {
        name: string; status: string; range?: { start: string; end: string }; message?: string;
        source?: string; queried_at?: string[];
      };
      const labels: Record<string, string> = {
        read_skill: "已读取经营分析技能", read_skill_resource: "已读取指标口径参考",
        store_overview: "已查询经营概览",
        store_data_catalog: "已发现可查询数据", store_query: "已执行针对性查询",
        calculate: "已完成计算", store_chart: "已准备图表，完成后保存",
      };
      const text = data.source === "saved_chart"
        ? `${data.status === "partial" ? "历史图部分读取" : "已读取保存图快照"}：原查询时间 ${data.queried_at?.join("、") ?? "见回答"}`
        : data.status === "completed"
        ? (labels[data.name] ?? "查询已完成") + (data.range ? `：${data.range.start} 至 ${data.range.end}` : "")
        : (data.name === "store_query" ? `${data.status === "partial" ? "查询部分完成" : "查询未完成"}：${data.message ?? "请查看逐项结果。"}`
          : data.name === "calculate" ? `计算未完成：${data.message ?? "请求未获执行。"}`
          : data.name === "store_chart" ? `图表未生成：${data.message ?? "请求未获执行。"}` : "本次工具请求未获执行");
      setActivity({ runId, text });
    });
    source.addEventListener("delta", (event) => {
      if (!current()) return;
      const id = Number((event as MessageEvent).lastEventId);
      if (id && id <= lastEventId) return;
      if (id) lastEventId = id;
      output += (JSON.parse((event as MessageEvent).data) as { text: string }).text;
      setConversation((previous) => previous?.run?.id === runId
        ? { ...previous, run: { ...previous.run, output } } : previous);
    });
    source.addEventListener("completed", () => {
      source.close();
      if (current()) { setActivity(null); void reload(); }
    });
    source.addEventListener("failed", (event) => {
      source.close();
      if (!current()) return;
      const { error_code } = JSON.parse((event as MessageEvent).data) as { error_code: string };
      if (error_code === "reset") {
        epoch.current++;
        pending.current = null;
        setSending(false);
        void reload();
        return;
      }
      setConversation((previous) => previous?.run?.id === runId
        ? { ...previous, run: { ...previous.run, status: "failed", error_code } } : previous);
    });
    source.onerror = () => {
      if (current()) setConnection("连接暂时中断，正在重连。你也可以刷新页面读取已保存的回答。");
    };
    return () => { disposed = true; source.close(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, status, base, controlling]);

  async function send(content = draft) {
    if (sending || controlling || status === "running" || !content.trim() || !conversation) return;
    const version = epoch.current;
    const chatGeneration = conversation.generation ?? 0;
    if (!pending.current || pending.current.content !== content || pending.current.generation !== chatGeneration) {
      pending.current = { content, request_id: crypto.randomUUID(), generation: chatGeneration };
    }
    setSending(true);
    followLatest.current = true;
    setAwayFromBottom(false);
    setError("");
    try {
      const run = await api<Run>(`${base}/messages`, { method: "POST", body: JSON.stringify(pending.current) });
      if (!valid(version)) return;
      pending.current = null;
      reads.current++;
      setDraft("");
      setConversation((previous) => previous && { ...previous, run });
      await reload();
    } catch (cause) {
      if (valid(version)) {
        // Keep the request identity when its response is lost; retries must reuse it.
        await reload();
        if (valid(version)) setError(friendlyApiError(cause, "发送结果未确认，已尝试重新读取对话，请确认后再发送。"));
      }
    } finally {
      if (valid(version)) setSending(false);
    }
  }

  async function older() {
    if (!conversation?.next_before || loadingOlder) return;
    setLoadingOlder(true);
    const version = epoch.current;
    try {
      const history = await api<Conversation>(`${base}/conversation?before=${conversation.next_before}`);
      if (valid(version)) {
        if (transcript.current) olderScroll.current = { height: transcript.current.scrollHeight, top: transcript.current.scrollTop };
        setConversation((previous) => previous && {
          ...previous, messages: [...history.messages, ...previous.messages], next_before: history.next_before,
        });
      }
    } catch (cause) {
      if (valid(version)) setError(friendlyApiError(cause, "历史对话加载失败，请重试"));
    } finally {
      if (valid(version)) setLoadingOlder(false);
    }
  }

  async function control(action: "stop" | "reset") {
    if (!conversation || controlling) return;
    const version = ++epoch.current;
    reads.current++;
    setControlling(true);
    setSending(false);
    setLoadingOlder(false);
    setConnection("");
    pending.current = null;
    try {
      if (action === "reset") {
        const value = await api<Conversation>(`${base}/conversation/reset`, {
          method: "POST", body: JSON.stringify({ generation: conversation.generation ?? 0 }),
        });
        if (valid(version)) {
          followLatest.current = true;
          olderScroll.current = null;
          setAwayFromBottom(false);
          setConversation(value); setDraft(""); setError("");
        }
      } else if (runId) {
        const value = await api<Run>(`${base}/runs/${runId}/stop`, { method: "POST" });
        if (valid(version)) {
          setConversation((previous) => previous && { ...previous, run: value });
          setError("");
        }
      }
    } catch (cause) {
      if (valid(version)) {
        await reload();
        if (valid(version)) setError(friendlyApiError(cause, "操作结果未确认，请重新读取对话。"));
      }
    } finally {
      if (valid(version)) setControlling(false);
    }
  }

  return <div className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_19rem]">
    <section aria-label="AI 聊天" className="flex h-[calc(100dvh-10rem)] min-h-[22rem] min-w-0 flex-col overflow-hidden rounded-2xl border bg-card shadow-sm md:h-[calc(100dvh-3rem)] md:min-h-[30rem]">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b px-3 py-2.5 sm:px-5">
        <div className="flex items-center gap-2.5 text-sm font-semibold"><span className="grid size-9 place-items-center rounded-xl bg-primary/10"><MessageSquare aria-hidden="true" className="size-4 text-primary" /></span><div>门店助手<p className="mt-0.5 text-[11px] font-normal text-muted-foreground">通用问答 · 经营分析</p></div></div>
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setExampleIndex(0)}>示例会话</Button>
          {status === "running" && <Button size="sm" variant="outline" disabled={controlling} onClick={() => void control("stop")}><Square aria-hidden="true" />停止生成</Button>}
          {status === "failed" && conversation?.messages.at(-1)?.role === "user" && <Button size="sm" variant="outline" disabled={sending || controlling} onClick={() => void send(conversation.messages.at(-1)!.content)}>重试</Button>}
          <Button aria-label="重置对话" size="sm" variant="ghost" disabled={!conversation || controlling} onClick={() => void control("reset")}><RotateCcw aria-hidden="true" /><span className="hidden sm:inline">重置对话</span></Button>
        </div>
      </div>
      <AgentChartCache key={`${conversation?.generation ?? 0}:${epoch.current}`}><div ref={transcript} role="region" aria-label="聊天记录" tabIndex={0}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-gradient-to-b from-primary/[0.025] to-muted/25 px-3 py-5 sm:px-5"
        onScroll={(event) => {
          const element = event.currentTarget;
          const following = element.scrollHeight - element.scrollTop - element.clientHeight < 96;
          followLatest.current = following;
          setAwayFromBottom(!following);
        }}>
        <div className="grid min-w-0 content-start gap-5">
          {!conversation && !error && <p role="status" className="py-6 text-center text-sm text-muted-foreground">正在读取对话…</p>}
          {conversation?.next_before && <Button className="justify-self-center" size="sm" variant="outline" disabled={loadingOlder} onClick={() => void older()}>读取更早对话</Button>}
          {conversation && !conversation.messages.length && !conversation.run && <div className="grid justify-items-center gap-3 px-3 py-8 text-center sm:py-12">
            <span aria-hidden="true" className="grid size-14 place-items-center rounded-2xl bg-primary/10 text-primary"><Bot className="size-7" /></span>
            <div><h2 className="font-semibold">今天有什么想聊的？</h2><p className="mt-2 max-w-sm text-sm leading-6 text-muted-foreground">可以聊日常问题，也可以查询当前门店的经营情况。</p></div>
          </div>}
          {conversation?.messages.map((message) => <ChatMessage key={message.id} role={message.role} content={message.content}>
            {[...new Map((message.charts ?? []).map((chart) => [chart.chart_id, chart])).values()].map((chart) =>
              <AgentChart key={chart.chart_id} storeId={storeId} messageId={message.id} description={chart} />)}
          </ChatMessage>)}
          {conversation?.run && status !== "completed" && <ChatMessage content={conversation.run.output}>
            {status === "running" ? <p role="status" className="mt-2 flex items-center gap-2 text-xs text-muted-foreground"><span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-primary" />正在生成回答…</p>
              : <p role="alert" className="mt-2 text-sm text-destructive">回答失败：{failures[conversation.run.error_code ?? ""] ?? "处理失败，请稍后重新发送。"}</p>}
          </ChatMessage>}
        </div>
      </div></AgentChartCache>
      <div className="shrink-0 border-t bg-card p-3 sm:px-5 sm:py-3.5">
        <ChatQuestionButtons disabled={!conversation || sending || controlling || status === "running"} onSelect={(prompt) => {
          const next = draft.trim() ? `${draft}\n\n${prompt}` : prompt;
          if (next.length > 6000) {
            setError("加入问题后超过 6,000 字，请先缩短输入内容。");
            return;
          }
          setDraft(next);
          composer.current?.focus();
        }} />
        {awayFromBottom && <div className="mb-2 flex justify-center"><Button size="sm" variant="secondary" onClick={() => {
          followLatest.current = true;
          setAwayFromBottom(false);
          if (transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight;
        }}><ArrowDown aria-hidden="true" />回到最新消息</Button></div>}
        {error && <div role="alert" className="mb-3 flex flex-wrap items-center gap-2 text-sm text-destructive">{error}<Button size="sm" variant="outline" onClick={() => void reload()}>重新读取</Button></div>}
        {status === "completed" && <p role="status" className="mb-2 text-xs text-muted-foreground">回答已完成并保存</p>}
        {status === "running" && connection && <p role="status" className="mb-2 text-xs text-muted-foreground">{connection}</p>}
        {activity && activity.runId === runId && <p role="status" className="mb-2 text-xs text-muted-foreground">{activity.text}</p>}
        <form onSubmit={(event) => { event.preventDefault(); void send(); }}>
          <label htmlFor="chat-message" className="sr-only">发送消息</label>
          <div className="flex items-end gap-2 rounded-xl border bg-background/50 p-2 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20">
            <textarea ref={composer} id="chat-message" rows={2} placeholder="输入消息，或选择上方问题…" className="max-h-36 min-h-16 w-full resize-none border-0 bg-transparent px-2 py-1.5 text-sm leading-6 focus-visible:outline-none" maxLength={6000} value={draft}
              onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
                  event.preventDefault();
                  void send();
                }
              }} />
            <Button className="shrink-0 whitespace-nowrap" type="submit" disabled={!conversation || sending || controlling || status === "running" || !draft.trim()}><ArrowUp aria-hidden="true" /><span>发送</span></Button>
          </div>
          <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <p className="min-w-0">Enter 发送 · Shift + Enter 换行</p><span className="shrink-0">{draft.length.toLocaleString()} / 6,000</span>
          </div>
        </form>
      </div>
    </section>
    <aside aria-label="对话辅助" className="grid min-w-0 gap-4 xl:max-h-[calc(100dvh-3rem)] xl:overflow-y-auto">
      <ChatExamplePreview onOpen={setExampleIndex} />
      <AgentMemoryPanel storeId={storeId} />
    </aside>
    <Dialog open={exampleIndex !== null} onOpenChange={(open) => { if (!open) setExampleIndex(null); }}>
      <DialogContent className="max-w-2xl" onCloseAutoFocus={(event) => { event.preventDefault(); composer.current?.focus(); }}>
        <DialogHeader><DialogTitle>示例会话</DialogTitle><DialogDescription>看看如何提问和追问，然后回到聊天试一试。</DialogDescription></DialogHeader>
        <ChatExamples key={exampleIndex} initialExample={exampleIndex ?? 0} />
      </DialogContent>
    </Dialog>
  </div>;
}

export function AgentChatPage() {
  const { user } = useAuth();
  const { selected } = useStore();
  if (user?.role !== "admin") return <Navigate to="/" replace />;
  return <section className="mx-auto grid min-w-0 max-w-6xl gap-4">
    {selected ? <Chat key={`${currentSessionScope()}:${user.id}:${selected.id}`} storeId={selected.id} /> : <p>请先选择门店。</p>}
  </section>;
}
