import { useEffect, useRef, useState } from "react";

import { api, friendlyApiError } from "@/api/client";
import type { components } from "@/api/generated";
import { currentSessionScope } from "@/auth/sessionScope";
import { Button } from "@/components/ui/button";

type MemoryList = components["schemas"]["MemoryList"];

export function AgentMemoryPanel({ storeId }: { storeId: number }) {
  const [value, setValue] = useState<MemoryList | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const active = useRef(false);
  const sequence = useRef(0);
  const session = useRef(currentSessionScope());
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; sequence.current++; };
  }, []);
  async function load(before?: string) {
    const request = ++sequence.current;
    const valid = () => active.current && sequence.current === request && session.current === currentSessionScope();
    setLoading(true);
    try {
      const next = await api<MemoryList>(`/agent/${storeId}/memories${before ? `?before=${before}` : ""}`);
      if (valid()) {
        setValue((previous) => before && previous ? { ...next, items: [...previous.items, ...next.items] } : next);
        setError("");
      }
    } catch (cause) {
      if (valid()) setError(friendlyApiError(cause, "记忆读取失败，请重试"));
    } finally {
      if (valid()) setLoading(false);
    }
  }
  async function moreSources(item: MemoryList["items"][number]) {
    const request = ++sequence.current;
    const valid = () => active.current && sequence.current === request && session.current === currentSessionScope();
    setLoading(true);
    try {
      const next = await api<components["schemas"]["MemorySourceList"]>(
        `/agent/${storeId}/memories/${item.id}/sources?before=${item.sources_next_before}`,
      );
      if (valid()) {
        setValue((previous) => previous && { ...previous, items: previous.items.map((memory) => memory.id === item.id
          ? { ...memory, sources: [...memory.sources, ...next.items], sources_next_before: next.next_before } : memory) });
        setError("");
      }
    } catch (cause) {
      if (valid()) setError(friendlyApiError(cause, "来源读取失败，请重试"));
    } finally {
      if (valid()) setLoading(false);
    }
  }
  return <section aria-label="AI 记忆" className="grid min-w-0 gap-3 rounded-xl border bg-card p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="font-semibold">AI 记忆</h2>
      <Button variant="outline" disabled={loading} onClick={() => void load()}>{value ? "刷新记忆" : "查看记忆"}</Button>
    </div>
    <p className="text-sm text-muted-foreground">发送“记住：……”保存长期偏好或门店背景，单条最多 2,000 字。重置聊天会保留已保存记忆；索引待处理表示尚不能通过向量检索使用。</p>
    {loading && <p role="status">正在读取记忆…</p>}
    {error && <p role="alert">{error}</p>}
    {value?.items.length === 0 && <p>当前管理员在此门店暂无记忆。</p>}
    {value?.items.map((item) => <article key={item.id} className="min-w-0 rounded-lg border p-3">
      <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{item.content}</p>
      <p className="mt-2 text-sm text-muted-foreground">
        {item.status === "pending_confirmation" ? "待确认，未生效（候选处理将在后续开放）" : "已保存"}
        {item.index_status === "pending" ? " · 索引待处理，向量检索尚未就绪" : ""}
        {item.index_status === "ready" ? " · 可向量检索" : ""}
        {item.index_status === "failed" ? " · 索引失败" : ""}
        {` · 版本 ${item.version} · 更新于 ${new Date(item.updated_at + (item.updated_at.endsWith("Z") ? "" : "Z")).toLocaleString()}`}
      </p>
      <details className="mt-2">
        <summary className="cursor-pointer text-sm">查看来源</summary>
        <ul className="mt-2 grid gap-2">
          {item.sources.map((source) => <li key={source.run_id} className="min-w-0 text-sm">
            <blockquote className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{source.evidence}</blockquote>
            <p className="break-all text-xs text-muted-foreground">来源消息 #{source.message_id} · 运行 {source.run_id}</p>
          </li>)}
        </ul>
        {item.sources_next_before && <Button variant="outline" disabled={loading} onClick={() => void moreSources(item)}>读取更早来源</Button>}
      </details>
    </article>)}
    {value?.next_before && <Button variant="outline" disabled={loading} onClick={() => void load(value.next_before!)}>读取更多记忆</Button>}
  </section>;
}
