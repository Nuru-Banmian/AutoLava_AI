import { useEffect, useRef, useState } from "react";

import { api, ApiError, friendlyApiError } from "@/api/client";
import type { components } from "@/api/generated";
import { currentSessionScope } from "@/auth/sessionScope";
import { Button } from "@/components/ui/button";

type MemoryList = components["schemas"]["MemoryList"];
type MemoryItem = MemoryList["items"][number];

export function AgentMemoryPanel({ storeId }: { storeId: number }) {
  const [value, setValue] = useState<MemoryList | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<{ id: string; version: number; content: string } | null>(null);
  const [confirm, setConfirm] = useState<MemoryItem | "clear" | null>(null);
  const [notice, setNotice] = useState("");
  const active = useRef(false);
  const sequence = useRef(0);
  const session = useRef(currentSessionScope());
  useEffect(() => {
    active.current = true;
    session.current = currentSessionScope();
    setValue(null);
    setEditing(null);
    setConfirm(null);
    setError("");
    setNotice("");
    setLoading(false);
    return () => { active.current = false; sequence.current++; };
  }, [storeId]);
  async function load(before?: string) {
    const request = ++sequence.current;
    const valid = () => active.current && sequence.current === request && session.current === currentSessionScope();
    setLoading(true);
    try {
      const next = await api<MemoryList>(`/agent/${storeId}/memories${before ? `?before=${before}` : ""}`);
      if (valid()) {
        if (before && value && next.revision !== value.revision) {
          setError("记忆已变化，请刷新后继续读取。");
          return;
        }
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
  async function mutate(action: "correct" | "delete" | "clear", item?: MemoryItem) {
    if (!value) return;
    const request = ++sequence.current;
    const valid = () => active.current && sequence.current === request && session.current === currentSessionScope();
    setLoading(true);
    setError("");
    setNotice("");
    try {
      if (action === "clear") {
        const next = await api<MemoryList>(`/agent/${storeId}/memories/clear`, {
          method: "POST", body: JSON.stringify({ expected_revision: value.revision }),
        });
        if (valid()) { setValue(next); setEditing(null); setConfirm(null); setNotice("记忆已全部清空。"); }
      } else if (action === "correct" && editing) {
        await api<MemoryItem>(`/agent/${storeId}/memories/${editing.id}`, {
          method: "PATCH", body: JSON.stringify({ expected_version: editing.version, content: editing.content }),
        });
        if (valid()) { setEditing(null); setNotice("纠正已保存。"); await load(); }
      } else if (action === "delete" && item) {
        await api(`/agent/${storeId}/memories/${item.id}`, {
          method: "DELETE", body: JSON.stringify({ expected_version: item.version }),
        });
        if (valid()) { setConfirm(null); setEditing(null); setNotice("记忆已删除。"); await load(); }
      }
    } catch (cause) {
      if (valid()) {
        setError(friendlyApiError(cause, "记忆变更失败，请重试"));
        setConfirm(null);
        if (cause instanceof ApiError && cause.status === 409 && action === "correct") {
          const body = cause.responseBody as { detail?: { current?: MemoryItem } } | undefined;
          const current = body?.detail?.current;
          if (current && editing && current.id === editing.id) {
            setValue((previous) => previous && { ...previous, items: previous.items.map((m) => m.id === current.id ? current : m) });
            setEditing({ ...editing, version: current.version });
          }
        }
      }
    } finally { if (valid()) setLoading(false); }
  }
  return <section aria-label="AI 记忆" className="grid min-w-0 gap-3 rounded-xl border bg-card p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="font-semibold">AI 记忆</h2>
      <Button variant="outline" disabled={loading} onClick={() => void load()}>{value ? "刷新记忆" : "查看记忆"}</Button>
      {value && <Button variant="outline" disabled={loading} onClick={() => setConfirm("clear")}>全部清空</Button>}
    </div>
    <p className="text-sm text-muted-foreground">发送“记住：……”保存长期偏好或门店背景，单条最多 2,000 字。重置聊天会保留已保存记忆；索引待处理表示尚不能通过向量检索使用。</p>
    <p className="text-sm text-muted-foreground">删除记忆与删除聊天不同：旧聊天原文可能仍可见，也可能仍在当前聊天上下文中。清空记忆不会清空聊天或门店描述；今后重新要求记住，可以形成新记忆。</p>
    {loading && <p role="status">正在读取记忆…</p>}
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {confirm && <div role="alertdialog" aria-label={confirm === "clear" ? "清空当前范围记忆" : "删除此条记忆"} className="grid gap-2 rounded-lg border p-3">
      <p>{confirm === "clear" ? "确认清空当前管理员在此门店的全部有效记忆和候选记忆？" : "确认删除此条记忆？"}</p>
      <div className="flex gap-2">
        <Button disabled={loading} onClick={() => void mutate(confirm === "clear" ? "clear" : "delete", confirm === "clear" ? undefined : confirm)}>{confirm === "clear" ? "确认清空" : "确认删除"}</Button>
        <Button variant="outline" disabled={loading} onClick={() => setConfirm(null)}>取消</Button>
      </div>
    </div>}
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
      <div className="mt-2 flex gap-2">
        <Button variant="outline" disabled={loading} onClick={() => { setEditing({ id: item.id, version: item.version, content: item.content }); setError(""); }}>纠正</Button>
        <Button variant="outline" disabled={loading} onClick={() => setConfirm(item)}>删除</Button>
      </div>
      {editing?.id === item.id && <form className="mt-2 grid gap-2" onSubmit={(event) => { event.preventDefault(); void mutate("correct"); }}>
        <label htmlFor={`memory-${item.id}`}>纠正内容</label>
        <textarea id={`memory-${item.id}`} className="min-h-24 w-full rounded border p-2" maxLength={2000} value={editing.content} disabled={loading}
          onChange={(event) => setEditing({ ...editing, content: event.target.value })} />
        {item.status === "pending_confirmation" && <p className="text-sm text-muted-foreground">纠正候选内容后仍需后续确认才能生效。</p>}
        <div className="flex gap-2">
          <Button type="submit" disabled={loading || !editing.content.trim()}>保存纠正</Button>
          <Button type="button" variant="outline" disabled={loading} onClick={() => setEditing(null)}>取消纠正</Button>
        </div>
      </form>}
      {!!item.changes?.length && <details className="mt-2 text-sm"><summary>最近纠正记录（最多 20 条）</summary>
        {item.changes.map((change) => <p className="whitespace-pre-wrap break-words" key={change.version}>版本 {change.version}：{change.previous_content} → {change.content}</p>)}
      </details>}
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
