import { useEffect, useRef, useState } from "react";
import { Navigate } from "react-router-dom";

import { api, friendlyApiError } from "@/api/client";
import type { components } from "@/api/generated";
import { useAuth } from "@/auth/AuthProvider";
import { currentSessionScope } from "@/auth/sessionScope";
import { Button } from "@/components/ui/button";
import { useStore } from "@/stores/StoreProvider";

type Conversation = components["schemas"]["ChatConversation"];
type Run = components["schemas"]["ChatRun"];

const failures: Record<string, string> = {
  model_not_configured: "聊天模型尚未配置，请联系管理员。",
  model_configuration: "模型配置或访问权限有误，请联系管理员。",
  model_timeout: "模型响应超时，请稍后重新发送。",
  model_rate_limited: "模型请求过于频繁，请稍后重新发送。",
  model_unavailable: "模型服务暂时不可用，请稍后重新发送。",
  model_format: "模型返回的内容不完整或格式不受支持。",
  output_budget: "回答达到输出上限，请缩小问题范围。",
  access_revoked: "当前会话或门店权限已失效。",
  interrupted: "本次回答已中断。",
  cancelled: "本次回答已停止。",
  reset: "对话已重置。",
};

function Chat({ storeId }: { storeId: number }) {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("");
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [controlling, setControlling] = useState(false);
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
  useEffect(() => {
    if (!runId || status !== "running" || controlling) return;
    const version = epoch.current;
    const source = new EventSource(`/api${base}/runs/${runId}/events`, { withCredentials: true });
    let output = "";
    let disposed = false;
    let lastEventId = 0;
    const current = () => !disposed && valid(version);
    source.onopen = () => { if (current()) setConnection(""); };
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
      if (current()) void reload();
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
      if (valid(version)) setConversation((previous) => previous && {
        ...previous, messages: [...history.messages, ...previous.messages], next_before: history.next_before,
      });
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
        if (valid(version)) { setConversation(value); setDraft(""); setError(""); }
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

  return <div className="grid min-w-0 gap-4">
    <div className="flex gap-2">
      {status === "running" && <Button variant="outline" disabled={controlling} onClick={() => void control("stop")}>停止生成</Button>}
      <Button variant="outline" disabled={!conversation || controlling} onClick={() => void control("reset")}>重置对话</Button>
      {status === "failed" && conversation?.messages.at(-1)?.role === "user" && <Button variant="outline" disabled={sending || controlling} onClick={() => void send(conversation.messages.at(-1)!.content)}>重试</Button>}
    </div>
    {!conversation && !error && <p role="status">正在读取对话…</p>}
    {error && <div role="alert" className="text-destructive">{error} <Button variant="outline" onClick={() => void reload()}>重新读取</Button></div>}
    <div aria-label="聊天记录" className="grid min-w-0 gap-3">
      {conversation?.next_before && <Button variant="outline" disabled={loadingOlder} onClick={() => void older()}>读取更早对话</Button>}
      {conversation?.messages.map((message) => <article key={message.id} className="min-w-0 rounded-xl border bg-card p-4">
        <p className="mb-2 text-sm font-semibold text-muted-foreground">{message.role === "user" ? "你" : "AI 助手"}</p>
        <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{message.content}</p>
      </article>)}
      {conversation?.run && status !== "completed" && <article className="min-w-0 rounded-xl border bg-card p-4">
        <p className="mb-2 text-sm font-semibold">AI 助手</p>
        <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{conversation.run.output}</p>
        {status === "running" ? <p role="status">正在生成回答…</p>
          : <p role="alert" className="text-destructive">回答失败：{failures[conversation.run.error_code ?? ""] ?? "处理失败，请稍后重新发送。"}</p>}
      </article>}
    </div>
    {status === "completed" && <p role="status" className="text-sm text-muted-foreground">回答已完成并保存</p>}
    {status === "running" && connection && <p role="status">{connection}</p>}
    <form className="grid gap-2" onSubmit={(event) => { event.preventDefault(); void send(); }}>
      <label htmlFor="chat-message" className="font-semibold">发送消息</label>
      <textarea id="chat-message" className="min-h-28 w-full rounded-lg border bg-card p-3" maxLength={6000} value={draft} onChange={(event) => setDraft(event.target.value)} />
      <div className="flex items-center justify-between gap-3"><p className="text-xs text-muted-foreground">最多 6,000 字；当前版本支持通用聊天。</p><Button type="submit" disabled={!conversation || sending || controlling || status === "running" || !draft.trim()}>发送</Button></div>
    </form>
  </div>;
}

export function AgentChatPage() {
  const { user } = useAuth();
  const { selected } = useStore();
  if (user?.role !== "admin") return <Navigate to="/" replace />;
  return <section className="mx-auto grid min-w-0 max-w-3xl gap-5">
    <div><h1 className="text-2xl font-semibold">AI 对话</h1><p className="mt-1 text-sm text-muted-foreground">{selected?.name} · 对话仅对当前管理员可见，按门店分别保存。</p></div>
    {selected ? <Chat key={`${currentSessionScope()}:${user.id}:${selected.id}`} storeId={selected.id} /> : <p>请先选择门店。</p>}
  </section>;
}
