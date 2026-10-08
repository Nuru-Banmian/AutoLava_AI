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
  const [jobs, setJobs] = useState<components["schemas"]["MemoryJobList"] | null>(null);
  const [jobError, setJobError] = useState("");
  const jobSequence = useRef(0);
  const jobStates = useRef(new Map<number, string>());
  const mutationId = useRef<number | null>(null);
  const refreshPending = useRef(false);
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
    setJobs(null);
    setJobError("");
    jobStates.current.clear();
    mutationId.current = null;
    refreshPending.current = false;
    return () => { active.current = false; sequence.current++; jobSequence.current++; };
  }, [storeId]);
  async function loadJobs(before?: number) {
    const request = ++jobSequence.current;
    const valid = () => active.current && jobSequence.current === request && session.current === currentSessionScope();
    try {
      const next = await api<components["schemas"]["MemoryJobList"]>(`/agent/${storeId}/memory-jobs${before ? `?before=${before}` : ""}`);
      if (valid()) {
        const completed = next.items.some((job) => job.status === "completed"
          && ["pending", "running"].includes(jobStates.current.get(job.id) ?? ""));
        for (const job of next.items) jobStates.current.set(job.id, job.status);
        setJobs((previous) => before && previous ? { ...next, items: [...previous.items, ...next.items] } : next);
        setJobError("");
        if (completed) {
          if (mutationId.current !== null) refreshPending.current = true;
          else void load(undefined, false);
        }
      }
    } catch (cause) { if (valid()) setJobError(friendlyApiError(cause, "整理状态读取失败，请重试")); }
  }
  const processing = jobs?.items.some((job) => job.status === "pending" || job.status === "running");
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => void loadJobs(), 2000);
    return () => window.clearInterval(timer);
  }, [processing, storeId]);
  async function load(before?: string, refreshJobs = true) {
    if (!before && refreshJobs) void loadJobs();
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
  async function retryIndex() {
    const request = ++sequence.current;
    const valid = () => active.current && sequence.current === request && session.current === currentSessionScope();
    setLoading(true);
    try {
      const result = await api<{ scheduled: number }>(`/agent/${storeId}/memory-index/retry`, { method: "POST" });
      if (valid()) {
        setNotice(result.scheduled ? "已安排重试，请稍后刷新记忆查看索引状态。" : "没有需要重试的索引任务，请重新提问以重试检索。");
        await load();
      }
    } catch (cause) {
      if (valid()) setError(friendlyApiError(cause, "索引重试失败，请重试"));
    } finally { if (valid()) setLoading(false); }
  }
  async function mutate(action: "correct" | "delete" | "clear" | "accept" | "reject" | "editAccept", item?: MemoryItem) {
    if (!value) return;
    const request = ++sequence.current;
    mutationId.current = request;
    const valid = () => active.current && sequence.current === request && session.current === currentSessionScope();
    setLoading(true);
    setError("");
    setNotice("");
    try {
      if ((action === "accept" || action === "reject" || action === "editAccept") && item) {
        await api(`/agent/${storeId}/memories/${item.id}/${action === "reject" ? "reject" : "confirm"}`, {
          method: "POST", body: JSON.stringify({ expected_version: editing?.id === item.id ? editing.version : item.version,
            ...(action === "editAccept" && editing ? { content: editing.content } : {}) }),
        });
        if (valid()) { setEditing(null); setNotice(action === "reject" ? "候选已拒绝。" : "候选已确认。索引待处理。"); await load(); }
      } else if (action === "clear") {
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
    } finally {
      if (valid()) setLoading(false);
      if (mutationId.current === request) {
        mutationId.current = null;
        if (refreshPending.current) {
          refreshPending.current = false;
          void load(undefined, false);
        }
      }
    }
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
    {value && <p role="status" className="text-sm">{({
      available: "记忆检索可用，回答仅参考本轮相关命中。",
      processing: "索引处理中，记忆检索受限；已保存内容仍可查看。",
      failed: "记忆检索或索引失败，检索受限；已保存内容仍保留，可重试索引或重新提问。",
      unavailable: "记忆检索受限：向量服务未配置或暂时不可用，已保存内容仍保留。",
    })[value.retrieval_status ?? "unavailable"]}</p>}
    {value && (value.retrieval_status === "failed" || value.items.some((item) => item.index_status === "failed")) &&
      <Button variant="outline" disabled={loading} onClick={() => void retryIndex()}>重试索引</Button>}
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
        {item.status === "pending_confirmation" ? "待确认，未生效" : "已保存"}
        {item.index_status === "pending" ? " · 索引待处理，向量检索尚未就绪" : ""}
        {item.index_status === "ready" ? " · 索引已同步（检索可用性见上方状态）" : ""}
        {item.index_status === "failed" ? ` · 索引失败，已尝试 ${item.index_attempts ?? 0} 次` : ""}
        {item.index_error_code ? ` · 最近索引错误：${item.index_error_code}` : ""}
        {` · 版本 ${item.version} · 更新于 ${new Date(item.updated_at + (item.updated_at.endsWith("Z") ? "" : "Z")).toLocaleString()}`}
      </p>
      <div className="mt-2 flex gap-2">
        {item.status === "pending_confirmation" && <Button disabled={loading} onClick={() => void mutate("accept", item)}>确认</Button>}
        <Button variant="outline" disabled={loading} onClick={() => { setEditing({ id: item.id, version: item.version, content: item.content }); setError(""); }}>{item.status === "pending_confirmation" ? "修改" : "纠正"}</Button>
        {item.status === "pending_confirmation"
          ? <Button variant="outline" disabled={loading} onClick={() => void mutate("reject", item)}>拒绝</Button>
          : <Button variant="outline" disabled={loading} onClick={() => setConfirm(item)}>删除</Button>}
      </div>
      {editing?.id === item.id && <form className="mt-2 grid gap-2" onSubmit={(event) => { event.preventDefault(); void mutate(item.status === "pending_confirmation" ? "editAccept" : "correct", item); }}>
        <label htmlFor={`memory-${item.id}`}>纠正内容</label>
        <textarea id={`memory-${item.id}`} className="min-h-24 w-full rounded border p-2" maxLength={2000} value={editing.content} disabled={loading}
          onChange={(event) => setEditing({ ...editing, content: event.target.value })} />
        <div className="flex gap-2">
          <Button type="submit" disabled={loading || !editing.content.trim()}>{item.status === "pending_confirmation" ? "修改后确认" : "保存纠正"}</Button>
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
    {jobError && <p role="alert">{jobError}</p>}
    {jobs && <details open={processing || jobs.items.some((job) => job.status === "failed")} className="min-w-0 text-sm">
      <summary>记忆整理状态</summary>
      {!jobs.items.length && <p>暂无整理任务。</p>}
      {jobs.items.map((job) => <p key={job.id} className="mt-2 break-words">
        来源消息 #{job.message_id} · {{ pending: "等待整理", running: "整理中", completed: "整理完成", failed: "整理失败", stale: "来源或版本已失效" }[job.status]}
        {` · 尝试 ${job.attempts} · 模型调用 ${job.calls}`}
        {job.error_code && ` · ${job.error_code}`}
        {!!job.failures.length && ` · 失败记录：${job.failures.map((failure) => String(failure.code)).join("、")}`}
      </p>)}
      {jobs.next_before && <Button variant="outline" onClick={() => void loadJobs(jobs.next_before!)}>读取更早整理任务</Button>}
    </details>}
  </section>;
}
