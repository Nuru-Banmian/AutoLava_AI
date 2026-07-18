import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { endOfMonth, format, isValid, parseISO, startOfMonth } from "date-fns";
import { useSearchParams } from "react-router-dom";
import { api, ApiError, friendlyApiError } from "@/api/client";
import type { DatabaseResponse, IncomeConfigResponse, LedgerBody, LedgerSaveResponse, RecordSnapshot, WeatherResponse } from "@/api/types";
import { LedgerDatePicker } from "@/components/LedgerDatePicker";
import { LedgerForm } from "@/components/LedgerForm";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { categoryCatalogKey, incomeConfigKey, invalidateUserData, ledgerMonthKey, ledgerRecordKey, recentKey, storeLocalToday } from "@/lib/user-api";
import { useStore } from "@/stores/StoreProvider";
import { useUnsavedChanges } from "@/navigation/UnsavedChanges";

function validDateParameter(value: string | null) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = parseISO(value);
  return isValid(parsed) && format(parsed, "yyyy-MM-dd") === value ? value : null;
}

export function LedgerPage() {
  const { selected } = useStore(); const client = useQueryClient(); const { markDirty, requestTransition } = useUnsavedChanges();
  const [searchParams, setSearchParams] = useSearchParams(); const hasDateParameter = searchParams.has("date"); const parameterDate = validDateParameter(searchParams.get("date"));
  const today = selected ? storeLocalToday(selected) : ""; const allowedParameterDate = today && parameterDate && parameterDate <= today ? parameterDate : null; const [dateSelection, setDateSelection] = useState<{ storeId: number | null; date: string }>({ storeId: null, date: "" }); const storedDate = dateSelection.storeId === selected?.id && dateSelection.date <= today ? dateSelection.date : ""; const date = hasDateParameter ? allowedParameterDate ?? today : storedDate || today; const [visibleMonth, setVisibleMonth] = useState(() => date.slice(0, 7)); const [calendarOpen, setCalendarOpen] = useState(false); const [pending, setPending] = useState<{ storeId: number; date: string; body: LedgerBody } | null>(null); const [message, setMessage] = useState(""); const [savedSubmission, setSavedSubmission] = useState<{ revision: number; storeId: number; date: string; body: LedgerBody; canonicalRequested: boolean; canonicalReady: boolean } | null>(null);
  const scopeRef = useRef({ storeId: selected?.id ?? null, date }); scopeRef.current = { storeId: selected?.id ?? null, date };
  useEffect(() => setDateSelection({ storeId: selected?.id ?? null, date }), [selected?.id, date]);
  useEffect(() => setVisibleMonth(date.slice(0, 7)), [selected?.id, date]);
  useEffect(() => { setPending(null); setMessage(""); setSavedSubmission(null); }, [selected?.id, date]);
  const catalog = useQuery({ queryKey: selected ? categoryCatalogKey(selected.id, date) : ["categoryCatalog", "none"], enabled: Boolean(selected && date), queryFn: () => api<DatabaseResponse>(`/database/${selected!.id}/records?start=${date}&end=${date}&page=1&page_size=1`) });
  const config = useQuery({ queryKey: selected ? incomeConfigKey(selected.id) : ["income-config", "none", "current"], enabled: Boolean(selected), queryFn: () => api<IncomeConfigResponse>(`/income-config/${selected!.id}/current`) });
  const record = useQuery({ queryKey: selected && date ? ledgerRecordKey(selected.id, date) : ["ledger", "record", "none"], enabled: Boolean(selected && date), queryFn: async () => { try { return await api<RecordSnapshot>(`/ledger/${selected!.id}/${date}`); } catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; } } });
  const monthRecords = useQuery<DatabaseResponse>({ queryKey: selected && visibleMonth ? ledgerMonthKey(selected.id, visibleMonth) : ["ledgerMonth", "none"], enabled: Boolean(selected && visibleMonth && calendarOpen), queryFn: ({ signal }) => {
    const monthDate = parseISO(`${visibleMonth}-01`);
    const start = format(startOfMonth(monthDate), "yyyy-MM-dd");
    const end = format(endOfMonth(monthDate), "yyyy-MM-dd");
    return api<DatabaseResponse>(`/database/${selected!.id}/records?start=${start}&end=${end}&page=1&page_size=200`, { signal });
  } });
  const recent = useQuery({ queryKey: selected ? recentKey(selected.id) : ["ledger", "recent", "none"], enabled: Boolean(selected), queryFn: () => api<RecordSnapshot[]>(`/ledger/${selected!.id}/recent?days=7`) });
  const weather = useQuery({ queryKey: ["weather", selected?.id, date], enabled: Boolean(selected && date), retry: false, queryFn: () => api<WeatherResponse>(`/weather/${selected!.id}/${date}`) });
  useEffect(() => {
    if (!savedSubmission?.canonicalRequested || savedSubmission.canonicalReady || !record.isSuccess || !record.data) return;
    setSavedSubmission((previous) => previous ? { ...previous, canonicalReady: true } : previous);
  }, [record.data, record.dataUpdatedAt, record.isSuccess, savedSubmission?.canonicalReady, savedSubmission?.canonicalRequested]);
  const currentSavedSubmission = savedSubmission && savedSubmission.storeId === selected?.id && savedSubmission.date === date ? savedSubmission : undefined;
  const recordedDates = useMemo(() => new Set([...(monthRecords.data?.items.map((item) => item.date) ?? []), ...(record.data ? [record.data.date] : [])]), [monthRecords.data, record.data]);
  const chooseDate = (nextDate: string) => requestTransition(() => {
    setDateSelection({ storeId: selected?.id ?? null, date: nextDate });
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("date", nextDate);
      return next;
    });
  });
  const save = useMutation({ mutationFn: ({ storeId, date: targetDate, body, overwrite = false }: { storeId: number; date: string; body: LedgerBody; overwrite?: boolean }) => api<LedgerSaveResponse>(`/ledger/${storeId}/${targetDate}${overwrite ? "?overwrite=true" : ""}`, { method: "PUT", body: JSON.stringify(body) }), onSuccess: async (_data, variables) => { if (scopeRef.current.storeId === variables.storeId && scopeRef.current.date === variables.date) { setSavedSubmission((previous) => ({ revision: (previous?.revision ?? 0) + 1, storeId: variables.storeId, date: variables.date, body: variables.body, canonicalRequested: false, canonicalReady: false })); setPending(null); } await invalidateUserData(client, variables.storeId); if (scopeRef.current.storeId === variables.storeId && scopeRef.current.date === variables.date) { const canonical = client.getQueryState<RecordSnapshot | null>(ledgerRecordKey(variables.storeId, variables.date)); setSavedSubmission((previous) => previous?.body === variables.body ? { ...previous, canonicalRequested: true, canonicalReady: canonical?.status === "success" && Boolean(canonical.data) } : previous); } }, onError: async (error, variables) => { const current = scopeRef.current.storeId === variables.storeId && scopeRef.current.date === variables.date; if (error instanceof ApiError && error.status === 409 && error.detail.includes("configuration version") && current) { setPending(null); setMessage(friendlyApiError(error, "保存失败，请重试")); await Promise.all([client.invalidateQueries({ queryKey: incomeConfigKey(variables.storeId), exact: true }), client.invalidateQueries({ queryKey: ledgerRecordKey(variables.storeId, variables.date), exact: true })]); return; } if (error instanceof ApiError && error.status === 409 && !variables.overwrite && current) setPending({ storeId: variables.storeId, date: variables.date, body: variables.body }); else if (current) setMessage(friendlyApiError(error, "保存失败，请重试")); } });
  if (!selected) return <section><h1 className="text-2xl font-semibold">每日台账</h1><p role="status">请先选择门店。</p></section>;
  return <section className="grid min-w-0 gap-6"><header className="flex min-w-0 flex-wrap items-center justify-between gap-3"><h1 className="text-2xl font-semibold">每日台账</h1><LedgerDatePicker value={date || today} today={today} recordedDates={recordedDates} onChange={chooseDate} onMonthChange={setVisibleMonth} onOpenChange={setCalendarOpen} /></header>
    {selected.is_active === false ? <p role="status">该门店已归档，台账仅供查看；可在历史记录和经营分析中查看数据。</p> : catalog.isLoading || config.isLoading || record.isLoading ? <p role="status">加载台账…</p> : config.error ? <div role="alert"><span>{friendlyApiError(config.error, "收入配置加载失败，请稍后重试")}</span><button className="ml-2 underline" onClick={() => void config.refetch()}>重试收入配置</button></div> : catalog.error || (record.error && !record.data && !currentSavedSubmission) ? <p role="alert">{friendlyApiError(catalog.error ?? record.error, "台账加载失败，请稍后重试")}</p> : <LedgerForm key={`${selected.id}:${date}`} categories={catalog.data?.categories ?? []} config={config.data!} record={record.data ?? undefined} recordRevision={record.dataUpdatedAt} weather={weather.data} saving={save.isPending} submitLabel={record.data ? "保存修改" : date === today ? "保存今日记录" : "补记历史记录"} savedSubmission={currentSavedSubmission} onDirtyChange={markDirty} onSavedSubmissionApplied={(revision) => { if (currentSavedSubmission?.revision === revision) setMessage("保存成功"); }} onSave={(body) => { setMessage(""); save.mutate({ storeId: selected.id, date, body }); }} />}
    {record.error && (record.data || currentSavedSubmission) && <p role="alert">台账刷新失败，请稍后重试<button className="ml-2 underline" onClick={() => void record.refetch()}>重试台账</button></p>}
    {message && <p role={message === "保存成功" ? "status" : "alert"}>{message}</p>}
    <aside><h2 className="text-lg font-semibold">最近七天</h2>{recent.isLoading ? <p role="status">加载最近记录…</p> : recent.error ? <div role="alert"><span>{friendlyApiError(recent.error, "最近记录加载失败，请稍后重试")}</span><button className="ml-2 underline" onClick={() => void recent.refetch()}>重试最近记录</button></div> : recent.data?.length ? <ul>{recent.data.map((item) => <li key={item.id}><button className="underline" onClick={() => chooseDate(item.date)}>{item.date} · {item.is_open}</button></li>)}</ul> : <p>暂无记录</p>}</aside>
    <AlertDialog open={Boolean(pending && pending.storeId === selected.id && pending.date === date)} onOpenChange={(open) => { if (!open) setPending(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>覆盖已有记录？</AlertDialogTitle><AlertDialogDescription>该日期已有记录，确认后将覆盖原内容。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => pending && save.mutate({ ...pending, overwrite: true })}>确认覆盖</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </section>;
}
