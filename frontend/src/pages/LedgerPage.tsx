import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { endOfMonth, format, isValid, parseISO, startOfMonth } from "date-fns";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, friendlyApiError } from "@/api/client";
import type { DatabaseResponse, IncomeConfigResponse, LedgerBody, LedgerSaveResponse, RecordSnapshot, WeatherResponse } from "@/api/types";
import { LedgerDatePicker } from "@/components/LedgerDatePicker";
import { LedgerForm } from "@/components/LedgerForm";
import { Button } from "@/components/ui/button";
import { categoryCatalogKey, incomeConfigKey, invalidateUserData, ledgerMonthKey, ledgerRecordKey, storeLocalToday } from "@/lib/user-api";
import { useStore } from "@/stores/StoreProvider";
import { useUnsavedChanges } from "@/navigation/UnsavedChanges";
import { ledgerReturnState } from "@/navigation/business-records-return";

function validDateParameter(value: string | null) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = parseISO(value);
  return isValid(parsed) && format(parsed, "yyyy-MM-dd") === value ? value : null;
}

export function LedgerPage() {
  const { selected } = useStore(); const client = useQueryClient(); const { markDirty, requestTransition, resetUnsavedChanges } = useUnsavedChanges();
  const location = useLocation(); const navigate = useNavigate(); const returnToBusinessRecords = ledgerReturnState(location.state);
  const [searchParams, setSearchParams] = useSearchParams(); const hasDateParameter = searchParams.has("date"); const parameterDate = validDateParameter(searchParams.get("date"));
  const today = selected ? storeLocalToday(selected) : ""; const allowedParameterDate = today && parameterDate && parameterDate <= today ? parameterDate : null; const [dateSelection, setDateSelection] = useState<{ storeId: number | null; date: string }>({ storeId: null, date: "" }); const storedDate = dateSelection.storeId === selected?.id && dateSelection.date <= today ? dateSelection.date : ""; const date = hasDateParameter ? allowedParameterDate ?? today : storedDate || today; const [visibleMonth, setVisibleMonth] = useState(() => date.slice(0, 7)); const [calendarOpen, setCalendarOpen] = useState(false); const [message, setMessage] = useState(""); const [savedSubmission, setSavedSubmission] = useState<{ revision: number; storeId: number; date: string; body: LedgerBody; canonicalRequested: boolean; canonicalReady: boolean } | null>(null);
  const scopeRef = useRef({ storeId: selected?.id ?? null, date }); scopeRef.current = { storeId: selected?.id ?? null, date };
  const [expected, setExpected] = useState<{ scope: string; identity: string | null; revision: number | null; configRevision: number } | null>(null);
  const [conflict, setConflict] = useState<{ kind: "record" | "config"; current: RecordSnapshot | null; config?: IncomeConfigResponse } | null>(null);
  const [priorDraft, setPriorDraft] = useState<{ scope: string; amounts: string } | null>(null);
  useEffect(() => setDateSelection({ storeId: selected?.id ?? null, date }), [selected?.id, date]);
  useEffect(() => setVisibleMonth(date.slice(0, 7)), [selected?.id, date]);
  useEffect(() => { setMessage(""); setSavedSubmission(null); setPriorDraft(null); }, [selected?.id, date]);
  const catalog = useQuery({ queryKey: selected ? categoryCatalogKey(selected.id, date) : ["categoryCatalog", "none"], enabled: Boolean(selected && date), queryFn: () => api<DatabaseResponse>(`/database/${selected!.id}/records?start=${date}&end=${date}&page=1&page_size=1`) });
  const config = useQuery({ queryKey: selected ? incomeConfigKey(selected.id) : ["income-config", "none", "current"], enabled: Boolean(selected), queryFn: () => api<IncomeConfigResponse>(`/income-config/${selected!.id}/current`) });
  const record = useQuery({ queryKey: selected && date ? ledgerRecordKey(selected.id, date) : ["ledger", "record", "none"], enabled: Boolean(selected && date), queryFn: async () => { try { return await api<RecordSnapshot>(`/ledger/${selected!.id}/${date}`); } catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; } } });
  const writeScope = `${selected?.id ?? "none"}:${date}`;
  useEffect(() => {
    if (record.isSuccess && config.data && expected?.scope !== writeScope) {
      setExpected({ scope: writeScope, identity: record.data?.identity ?? null, revision: record.data?.revision ?? null, configRevision: config.data.revision });
      setConflict(null);
    }
  }, [record.isSuccess, record.data, config.data, expected?.scope, writeScope]);
  const monthRecords = useQuery<DatabaseResponse>({ queryKey: selected && visibleMonth ? ledgerMonthKey(selected.id, visibleMonth) : ["ledgerMonth", "none"], enabled: Boolean(selected && visibleMonth && calendarOpen), queryFn: ({ signal }) => {
    const monthDate = parseISO(`${visibleMonth}-01`);
    const start = format(startOfMonth(monthDate), "yyyy-MM-dd");
    const end = format(endOfMonth(monthDate), "yyyy-MM-dd");
    return api<DatabaseResponse>(`/database/${selected!.id}/records?start=${start}&end=${end}&page=1&page_size=200`, { signal });
  } });
  const weather = useQuery({ queryKey: ["weather", selected?.id, date], enabled: Boolean(selected && date), retry: false, queryFn: () => api<WeatherResponse>(`/weather/${selected!.id}/${date}`) });
  const weatherOptions = useQuery({ queryKey: ["ledger", "weather-options"], queryFn: () => api<string[]>("/ledger/weather-options") });
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
  const save = useMutation({
    mutationFn: ({ storeId, date: targetDate, body, identity, revision, configRevision }: { storeId: number; date: string; body: LedgerBody; identity: string | null; revision: number | null; configRevision: number }) => api<LedgerSaveResponse>(`/ledger/${storeId}/${targetDate}`, { method: "PUT", body: JSON.stringify({ ...body, expected_identity: identity, expected_revision: revision, expected_config_revision: configRevision }) }),
    onSuccess: async (data, variables) => {
      const isCurrentScope = scopeRef.current.storeId === variables.storeId && scopeRef.current.date === variables.date;
      if (isCurrentScope) {
        setExpected({ scope: `${variables.storeId}:${variables.date}`, identity: data.identity, revision: data.revision, configRevision: data.config_revision ?? variables.configRevision });
        setConflict(null);
        setPriorDraft(null);
        setSavedSubmission((previous) => ({ revision: (previous?.revision ?? 0) + 1, storeId: variables.storeId, date: variables.date, body: variables.body, canonicalRequested: false, canonicalReady: false }));
        setMessage("保存成功");
      }
      await invalidateUserData(client, variables.storeId);
      if (scopeRef.current.storeId === variables.storeId && scopeRef.current.date === variables.date) {
        const canonical = client.getQueryState<RecordSnapshot | null>(ledgerRecordKey(variables.storeId, variables.date));
        setSavedSubmission((previous) => previous?.body === variables.body ? { ...previous, canonicalRequested: true, canonicalReady: canonical?.status === "success" && Boolean(canonical.data) } : previous);
      }
      const canReturnToBusinessRecords = returnToBusinessRecords?.storeId === variables.storeId
        && returnToBusinessRecords.range.start <= variables.date
        && variables.date <= returnToBusinessRecords.range.end;
      if (isCurrentScope && canReturnToBusinessRecords) {
        resetUnsavedChanges();
        navigate("/database", { replace: true, state: { restoreBusinessRecords: returnToBusinessRecords } });
      }
    },
    onError: (error, variables) => {
      if (scopeRef.current.storeId !== variables.storeId || scopeRef.current.date !== variables.date) return;
      const detail = error instanceof ApiError && typeof error.responseBody === "object" && error.responseBody !== null && "detail" in error.responseBody ? error.responseBody.detail : null;
      if (error instanceof ApiError && error.status === 409 && typeof detail === "object" && detail !== null && "code" in detail && detail.code === "ledger_revision_conflict") {
        setConflict({ kind: "record", current: "current" in detail ? detail.current as RecordSnapshot | null : null });
        setMessage("每日台账已变化，草稿已保留。请核对最新记录后再决定是否继续保存。");
      } else if (error instanceof ApiError && error.status === 409 && typeof detail === "object" && detail !== null && "code" in detail && detail.code === "income_config_revision_conflict") {
        setConflict({ kind: "config", current: "current_record" in detail ? detail.current_record as RecordSnapshot | null : null, config: "current_config" in detail ? detail.current_config as IncomeConfigResponse : undefined });
        setPriorDraft({ scope: `${variables.storeId}:${variables.date}`, amounts: variables.body.daily_revenue !== null ? `${variables.body.daily_revenue} 欧元` : variables.body.items.map((item) => `${config.data?.items.find((category) => category.id === item.category_id)?.name ?? item.category_id}：${item.amount} 欧元`).join("、") });
        setMessage("收入配置已变化，草稿已保留。请核对最新配置和金额后再决定是否继续保存。");
      } else if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        setMessage("当前没有记账权限，草稿已保留。请重新登录或联系管理员。");
      } else if (error instanceof ApiError && (error.status === 422 || error.status === 428)) {
        setMessage("提交参数有误，草稿已保留。请重新加载页面后核对。");
      } else setMessage(friendlyApiError(error, "保存失败，草稿已保留，请重试"));
    },
  });
  if (!selected) return <section><h1 className="text-2xl font-semibold">记账</h1><p role="status">请先选择门店。</p></section>;
  return <section className="min-w-0">
    <div className="mx-auto grid w-full max-w-4xl min-w-0 gap-4">
      <header className="flex min-w-0 flex-wrap items-center justify-between gap-3"><h1 className="text-2xl font-semibold">记账</h1><LedgerDatePicker value={date || today} today={today} recordedDates={recordedDates} onChange={chooseDate} onMonthChange={setVisibleMonth} onOpenChange={setCalendarOpen} /></header>
      <div role="region" aria-label="记账录入" className="grid min-w-0 gap-4 rounded-xl border bg-card p-4 text-card-foreground shadow-sm sm:p-6">
        {selected.is_active === false ? <p role="status">该门店已归档，台账仅供查看；可在历史记录和经营分析中查看数据。</p> : catalog.isLoading || config.isLoading || record.isLoading || weatherOptions.isLoading ? <p role="status">加载台账…</p> : config.error || weatherOptions.error ? <div role="alert"><span>{friendlyApiError(config.error ?? weatherOptions.error, "记账选项加载失败，请稍后重试")}</span><button className="ml-2 underline" onClick={() => { if (config.error) void config.refetch(); if (weatherOptions.error) void weatherOptions.refetch(); }}>{config.error ? "重试收入配置" : "重试天气选项"}</button></div> : catalog.error || (record.error && !record.data && !currentSavedSubmission) ? <div role="alert" className="grid justify-items-start gap-2"><p>{friendlyApiError(catalog.error ?? record.error, "台账加载失败，请稍后重试")}</p><Button variant="outline" onClick={() => { if (catalog.error) void catalog.refetch(); if (record.error) void record.refetch(); }}>重试台账</Button></div> : <LedgerForm key={`${selected.id}:${date}`} categories={catalog.data?.categories ?? []} config={config.data!} record={record.data ?? undefined} recordRevision={record.dataUpdatedAt} weather={weather.data} weatherOptions={weatherOptions.data ?? []} washCountEnabled={selected.wash_count_enabled ?? true} saving={save.isPending} submitLabel={record.data ? "保存修改" : date === today ? "保存今日记录" : "补记历史记录"} savedSubmission={currentSavedSubmission} onDirtyChange={markDirty} onSave={(body) => { if (expected?.scope !== writeScope || conflict) return; setMessage(""); save.mutate({ storeId: selected.id, date, body, identity: expected.identity, revision: expected.revision, configRevision: expected.configRevision }); }} />}
        {conflict && <div role="group" aria-label={conflict.kind === "config" ? "最新收入配置" : "最新每日台账"} className="space-y-2 rounded-md border p-3">
          {conflict.kind === "config" && <><p>最新收入配置修订号：{conflict.config?.revision ?? "未知"}；记账方式：{conflict.config?.enabled ? "分类记账" : "总额记账"}</p><p>最新项目：</p><ol>{[...(conflict.config?.items ?? [])].sort((left, right) => left.sort_order - right.sort_order).map((item) => <li key={item.id}>{item.sort_order + 1}. {item.name}；{item.include_in_total ? "计入营业额" : "不计入营业额"}；{item.is_active ? "启用" : "停用"}{item.archived_at ? "；已归档" : ""}</li>)}</ol><p>原草稿金额：{priorDraft?.amounts ?? "无"}</p></>}
          {conflict.current ? <>
            <p>{`最新记录：${conflict.current.is_open}，营业额 ${conflict.current.daily_revenue} 欧元，修订号 ${conflict.current.revision}`}</p>
            <p>洗车数量：{conflict.current.wash_count ?? "未记录"}；天气：{conflict.current.weather ?? "未记录"}</p>
            <p>事件：{conflict.current.activity ?? "无"}</p>
            {conflict.current.items.length > 0 && <ul>{conflict.current.items.map((item) => <li key={item.category_id}>{item.category_name}：{item.amount} 欧元</li>)}</ul>}
          </> : <p>最新记录：该日期暂无记录，原记录可能已删除。</p>}
          <button type="button" className="underline" disabled={conflict.kind === "config" && !conflict.config} onClick={() => { if (conflict.config) client.setQueryData(incomeConfigKey(selected.id), conflict.config); setExpected({ scope: writeScope, identity: conflict.current?.identity ?? null, revision: conflict.current?.revision ?? null, configRevision: conflict.config?.revision ?? expected?.configRevision ?? 1 }); setConflict(null); setMessage("已确认最新状态。请核对草稿后再次保存。"); }}>确认最新状态并继续编辑</button>
        </div>}
        {priorDraft?.scope === writeScope && !conflict && <p role="note">原草稿金额：{priorDraft.amounts}。请按最新记账方式重新核对并填写。</p>}
        {record.error && (record.data || currentSavedSubmission) && <p role="alert">台账刷新失败，请稍后重试<button className="ml-2 underline" onClick={() => void record.refetch()}>重试台账</button></p>}
        {message && <p role={message === "保存成功" ? "status" : "alert"}>{message}</p>}
      </div>
    </div>
  </section>;
}
