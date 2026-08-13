import { type FormEvent, useEffect, useRef, useState } from "react";

import { friendlyApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  sendAgentChatMessage,
  type AgentChatMessage,
} from "@/lib/agent-chat";
import { useStore } from "@/stores/StoreProvider";

export function AgentPage() {
  const { selected } = useStore();
  const [messages, setMessages] = useState<AgentChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const storeVersion = useRef(0);

  useEffect(() => {
    storeVersion.current += 1;
    setMessages([]);
    setDraft("");
    setError(null);
    setIsSending(false);
  }, [selected?.id]);

  async function send(event: FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!selected || !content || isSending) return;
    const nextMessages: AgentChatMessage[] = [
      ...messages,
      { role: "user", content },
    ];
    setMessages(nextMessages);
    setDraft("");
    setError(null);
    setIsSending(true);
    const requestStoreVersion = storeVersion.current;
    try {
      const response = await sendAgentChatMessage(selected.id, nextMessages.slice(-19));
      if (requestStoreVersion === storeVersion.current) {
        setMessages([...nextMessages, response.message]);
      }
    } catch (caught) {
      if (requestStoreVersion === storeVersion.current) {
        setError(friendlyApiError(caught, "AI 回复失败，请稍后重试"));
      }
    } finally {
      if (requestStoreVersion === storeVersion.current) {
        setIsSending(false);
      }
    }
  }

  return (
    <section className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold">AI 对话</h1>
        <p className="text-sm text-muted-foreground">当前为基础对话，刷新页面后记录会清空。</p>
      </div>
      <div
        aria-label="对话消息"
        className="min-h-64 flex-1 space-y-3 rounded-xl border bg-background p-4"
        role="log"
      >
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">发送一条消息开始对话。</p>
        )}
        {messages.map((message, index) => (
          <article
            className={message.role === "user" ? "ml-auto max-w-[85%] rounded-xl bg-primary px-4 py-3 text-primary-foreground" : "mr-auto max-w-[85%] rounded-xl bg-muted px-4 py-3"}
            key={`${message.role}-${index}`}
          >
            <span className="sr-only">{message.role === "user" ? "你" : "AI"}：</span>
            <p className="whitespace-pre-wrap text-sm">{message.content}</p>
          </article>
        ))}
        {isSending && <p className="text-sm text-muted-foreground" role="status">AI 正在回复…</p>}
      </div>
      <form className="grid gap-2" onSubmit={(event) => { void send(event); }}>
        <label className="sr-only" htmlFor="agent-message">消息</label>
        <textarea
          aria-label="消息"
          className="h-24 resize-none rounded-xl border bg-background p-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          disabled={!selected || isSending}
          id="agent-message"
          maxLength={4000}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={selected ? "输入消息…" : "请先选择门店"}
          value={draft}
        />
        <div className="flex items-center justify-between gap-3">
          <div>{error && <p className="text-sm text-destructive" role="alert">{error}</p>}</div>
          <Button disabled={!selected || !draft.trim() || isSending} type="submit">发送</Button>
        </div>
      </form>
    </section>
  );
}
