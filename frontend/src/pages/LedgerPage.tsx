import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/api/client";
import type { DatabaseResponse, LedgerBody, RecordSnapshot, WeatherResponse } from "@/api/types";
import { LedgerForm } from "@/components/LedgerForm";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { categoryCatalogKey, invalidateUserData, ledgerRecordKey, recentKey, storeLocalToday } from "@/lib/user-api";
import { useStore } from "@/stores/StoreProvider";

export function LedgerPage() {
  const { selected } = useStore(); const client = useQueryClient();
  const today = selected ? storeLocalToday(selected) : ""; const [date, setDate] = useState(today); const [pending, setPending] = useState<{ storeId: number; date: string; body: LedgerBody } | null>(null); const [message, setMessage] = useState("");
  const scopeRef = useRef({ storeId: selected?.id ?? null, date }); scopeRef.current = { storeId: selected?.id ?? null, date };
  useEffect(() => setDate(today), [selected?.id, today]);
  useEffect(() => { setPending(null); setMessage(""); }, [selected?.id, date]);
  const catalog = useQuery({ queryKey: selected ? categoryCatalogKey(selected.id, date) : ["categoryCatalog", "none"], enabled: Boolean(selected && date), queryFn: () => api<DatabaseResponse>(`/database/${selected!.id}/records?start=${date}&end=${date}&page=1&page_size=1`) });
  const record = useQuery({ queryKey: selected && date ? ledgerRecordKey(selected.id, date) : ["ledger", "record", "none"], enabled: Boolean(selected && date), queryFn: async () => { try { return await api<RecordSnapshot>(`/ledger/${selected!.id}/${date}`); } catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; } } });
  const recent = useQuery({ queryKey: selected ? recentKey(selected.id) : ["ledger", "recent", "none"], enabled: Boolean(selected), queryFn: () => api<RecordSnapshot[]>(`/ledger/${selected!.id}/recent?days=7`) });
  const weather = useQuery({ queryKey: ["weather", selected?.id, date], enabled: Boolean(selected && date), retry: false, queryFn: () => api<WeatherResponse>(`/weather/${selected!.id}/${date}`) });
  const save = useMutation({ mutationFn: ({ storeId, date: targetDate, body, overwrite = false }: { storeId: number; date: string; body: LedgerBody; overwrite?: boolean }) => api(`/ledger/${storeId}/${targetDate}${overwrite ? "?overwrite=true" : ""}`, { method: "PUT", body: JSON.stringify(body) }), onSuccess: async (_data, variables) => { if (scopeRef.current.storeId === variables.storeId && scopeRef.current.date === variables.date) { setPending(null); setMessage("保存成功"); } await invalidateUserData(client, variables.storeId); }, onError: (error, variables) => { const current = scopeRef.current.storeId === variables.storeId && scopeRef.current.date === variables.date; if (error instanceof ApiError && error.status === 409 && !variables.overwrite && current) setPending({ storeId: variables.storeId, date: variables.date, body: variables.body }); else if (current) setMessage(error instanceof ApiError ? error.detail : "保存失败"); } });
  if (!selected) return <section><h1 className="text-2xl font-semibold">每日台账</h1><p role="status">请先选择门店。</p></section>;
  return <section className="grid gap-6"><header><h1 className="text-2xl font-semibold">每日台账</h1><label>日期<input aria-label="日期" type="date" max={today} value={date} onChange={(event) => setDate(event.target.value)} className="ml-2 rounded border p-2" /></label></header>
    {catalog.isLoading || record.isLoading ? <p role="status">加载台账…</p> : catalog.error || record.error ? <p role="alert">{(catalog.error ?? record.error)?.message}</p> : <LedgerForm key={`${selected.id}:${date}`} categories={catalog.data?.categories ?? []} record={record.data ?? undefined} weather={weather.data} saving={save.isPending} onSave={(body) => { setMessage(""); save.mutate({ storeId: selected.id, date, body }); }} />}
    {message && <p role={message === "保存成功" ? "status" : "alert"}>{message}</p>}
    <aside><h2 className="text-lg font-semibold">最近七天</h2>{recent.isLoading ? <p role="status">加载最近记录…</p> : recent.error ? <div role="alert"><span>{recent.error.message}</span><button className="ml-2 underline" onClick={() => void recent.refetch()}>重试最近记录</button></div> : recent.data?.length ? <ul>{recent.data.map((item) => <li key={item.id}><button className="underline" onClick={() => setDate(item.date)}>{item.date} · {item.is_open}</button></li>)}</ul> : <p>暂无记录</p>}</aside>
    <AlertDialog open={Boolean(pending && pending.storeId === selected.id && pending.date === date)} onOpenChange={(open) => { if (!open) setPending(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>覆盖已有记录？</AlertDialogTitle><AlertDialogDescription>该日期已有记录，确认后将覆盖原内容。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => pending && save.mutate({ ...pending, overwrite: true })}>确认覆盖</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </section>;
}
