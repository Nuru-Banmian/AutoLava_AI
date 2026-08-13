import { type FormEvent, useEffect, useRef, useState } from "react";

import { friendlyApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  getAgentConversation,
  resetAgentConversation,
  sendAgentChatMessage,
  type AgentChatMessage,
} from "@/lib/agent-chat";
import { useStore } from "@/stores/StoreProvider";

export function AgentPage() {
  const { selected } = useStore();
  const [messages, setMessages] = useState<AgentChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [historyReady, setHistoryReady] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const storeVersion = useRef(0);
  const isCurrentStore = (requestStoreVersion: number) =>
    requestStoreVersion === storeVersion.current;

  useEffect(() => {
    storeVersion.current += 1;
    const requestStoreVersion = storeVersion.current;
    setMessages([]);
    setDraft("");
    setError(null);
    setIsSending(false);
    setIsResetting(false);
    setHistoryReady(false);
    if (!selected) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    void getAgentConversation(selected.id)
      .then((conversation) => {
        if (isCurrentStore(requestStoreVersion)) {
          setMessages(conversation.messages);
          setHistoryReady(true);
        }
      })
      .catch((caught) => {
        if (isCurrentStore(requestStoreVersion)) {
          setError(friendlyApiError(caught, "对话记录加载失败，请稍后重试"));
        }
      })
      .finally(() => {
        if (isCurrentStore(requestStoreVersion)) setIsLoading(false);
      });
  }, [selected?.id]);

  async function send(event: FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!selected || !content || !historyReady || isLoading || isSending || isResetting) return;
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
      const response = await sendAgentChatMessage(selected.id, content);
      if (isCurrentStore(requestStoreVersion)) {
        setMessages([...nextMessages, response.message]);
      }
    } catch (caught) {
      if (isCurrentStore(requestStoreVersion)) {
        setMessages(messages);
        setDraft(content);
        setError(friendlyApiError(caught, "AI 回复失败，请稍后重试"));
      }
    } finally {
      if (isCurrentStore(requestStoreVersion)) {
        setIsSending(false);
      }
    }
  }

  async function reset() {
    if (!selected || !historyReady || isLoading || isSending || isResetting) return;
    if (!window.confirm("确定重置当前门店的对话吗？此操作无法撤销。")) return;
    const requestStoreVersion = storeVersion.current;
    setError(null);
    setIsResetting(true);
    try {
      await resetAgentConversation(selected.id);
      if (isCurrentStore(requestStoreVersion)) {
        setMessages([]);
        setDraft("");
      }
    } catch (caught) {
      if (isCurrentStore(requestStoreVersion)) {
        setError(friendlyApiError(caught, "对话重置失败，请稍后重试"));
      }
    } finally {
      if (isCurrentStore(requestStoreVersion)) setIsResetting(false);
    }
  }

  return (
    <section className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">AI 对话</h1>
          <p className="text-sm text-muted-foreground">对话按管理员和门店保存，刷新后仍会保留。</p>
        </div>
        <Button
          disabled={!selected || !historyReady || isLoading || isSending || isResetting || messages.length === 0}
          onClick={() => { void reset(); }}
          type="button"
          variant="outline"
        >
          {isResetting ? "正在重置…" : "重置对话"}
        </Button>
      </div>
      <div
        aria-label="对话消息"
        className="min-h-64 flex-1 space-y-3 rounded-xl border bg-background p-4"
        role="log"
      >
        {isLoading && <p className="text-sm text-muted-foreground" role="status">正在加载对话…</p>}
        {!isLoading && messages.length === 0 && (
          <p className="text-sm text-muted-foreground">发送一条消息开始对话。</p>
        )}
        {messages.map((message, index) => (
          <article
            className={message.role === "user" ? "ml-auto w-fit max-w-[85%] break-words rounded-xl bg-primary px-4 py-3 text-primary-foreground" : "mr-auto w-fit max-w-[85%] break-words rounded-xl bg-muted px-4 py-3"}
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
          disabled={!selected || !historyReady || isLoading || isSending || isResetting}
          id="agent-message"
          maxLength={4000}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={selected ? "输入消息…" : "请先选择门店"}
          value={draft}
        />
        <div className="flex items-center justify-between gap-3">
          <div>{error && <p className="text-sm text-destructive" role="alert">{error}</p>}</div>
          <Button disabled={!selected || !historyReady || !draft.trim() || isLoading || isSending || isResetting} type="submit">发送</Button>
        </div>
      </form>
    </section>
  );
}
