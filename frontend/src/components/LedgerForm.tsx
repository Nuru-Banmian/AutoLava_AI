import { useEffect, useMemo, useState } from "react";
import type { CategoryDescriptor, IncomeConfigResponse, LedgerBody, LedgerStatus, RecordSnapshot, WeatherResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatWholeEuro, parseWholeAmount } from "@/lib/user-api";

const MANUAL_RECORD_WEATHER_OPTIONS = ["晴", "少云", "多云", "阴", "雾", "小雨", "中雨", "大雨", "阵雨", "雷雨"] as const;
const LEDGER_FIELD_CLASS = "min-h-11 w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-base shadow-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

export interface LedgerFormProps {
  categories: CategoryDescriptor[];
  config?: IncomeConfigResponse;
  record?: RecordSnapshot;
  weather?: WeatherResponse;
  onSave(body: LedgerBody): void;
  onDirtyChange?(dirty: boolean): void;
  saving?: boolean;
  submitLabel?: string;
  savedSubmission?: { revision: number; body: LedgerBody; canonicalReady?: boolean };
  recordRevision?: number;
}

function semanticAmount(value: string) {
  const result = parseWholeAmount(value);
  return "value" in result ? result.value : `invalid:${value}`;
}

export function LedgerForm({ categories, config, record, weather, onSave, onDirtyChange, saving = false, submitLabel = "保存", savedSubmission, recordRevision }: LedgerFormProps) {
  const resolvedConfig = useMemo(() => config ?? ({
    store_id: record?.store_id ?? 0,
    enabled: record?.income_mode === "composed",
    formula: "",
    items: categories.map((category) => ({ ...category, store_id: record?.store_id ?? 0, archived_at: null })),
  }), [categories, config, record]);
  const composed = record ? record.income_mode === "composed" : resolvedConfig.enabled;
  const active = useMemo(() => {
    if (record && composed) {
      return record.items.map((item) => ({
        id: item.category_id,
        name: item.category_name,
        include_in_total: item.include_in_total,
        is_active: true,
        sort_order: item.sort_order,
      })).sort((left, right) => left.sort_order - right.sort_order || left.id - right.id);
    }
    const configured = resolvedConfig.items
      .filter((item) => item.is_active)
      .map((item) => ({ id: item.id, name: item.name, include_in_total: item.include_in_total, is_active: item.is_active, sort_order: item.sort_order }));
    return configured.sort((left, right) => left.sort_order - right.sort_order || left.id - right.id);
  }, [categories, composed, resolvedConfig.items, record]);
  const [status, setStatus] = useState<LedgerStatus>(record?.is_open ?? "营业");
  const [wash, setWash] = useState(record?.wash_count == null ? "" : String(record.wash_count));
  const [weatherValue, setWeatherValue] = useState(record?.weather ?? weather?.weather ?? "");
  const [weatherEdited, setWeatherEdited] = useState(record?.weather_edited ?? false);
  const [activity, setActivity] = useState(record?.activity ?? "");
  const loadedDirectTotal = record ? String(record.daily_revenue) : "";
  const [directTotal, setDirectTotal] = useState(loadedDirectTotal);
  const loadedAmounts = useMemo(() => Object.fromEntries(active.map((category) => [category.id, record ? String(record.items.find((item) => item.category_id === category.id)?.amount ?? 0) : ""])), [active, record]);
  const [amounts, setAmounts] = useState<Record<number, string>>(loadedAmounts);
  const [validationError, setValidationError] = useState("");
  const [washActivityOpen, setWashActivityOpen] = useState(false);
  const incomingSignature = JSON.stringify({ record, recordRevision, loadedAmounts, automaticWeather: record ? null : weather?.weather ?? null });
  const semanticSignature = (values: { status: LedgerStatus; wash: string; weatherValue: string; weatherEdited: boolean; activity: string; directTotal: string; amounts: Record<number, string> }) => JSON.stringify({
    is_open: values.status,
    daily_revenue: composed ? null : semanticAmount(values.directTotal),
    wash_count: values.status === "休息" ? 0 : values.wash === "" ? null : Number(values.wash),
    weather: values.weatherValue || null,
    weather_edited: values.weatherEdited,
    activity: values.activity.trim() || null,
    items: composed ? active.map((category) => [category.id, semanticAmount(values.amounts[category.id] ?? "0")]) : [],
  });
  const submittedSignature = (body: LedgerBody) => JSON.stringify({
    is_open: body.is_open,
    daily_revenue: body.daily_revenue,
    wash_count: body.wash_count,
    weather: body.weather,
    weather_edited: body.weather_edited,
    activity: body.activity,
    items: body.items.map((item) => [item.category_id, item.amount]),
  });
  const loadedSemanticSignature = semanticSignature({ status: record?.is_open ?? "营业", wash: record?.wash_count == null ? "" : String(record.wash_count), weatherValue: record?.weather ?? weather?.weather ?? "", weatherEdited: record?.weather_edited ?? false, activity: record?.activity ?? "", directTotal: loadedDirectTotal, amounts: loadedAmounts });
  const [baselineSignature, setBaselineSignature] = useState(loadedSemanticSignature);
  const [appliedIncomingSignature, setAppliedIncomingSignature] = useState(incomingSignature);
  const [consumedSubmissionRevision, setConsumedSubmissionRevision] = useState<number | null>(null);
  const currentSignature = semanticSignature({ status, wash, weatherValue, weatherEdited, activity, directTotal, amounts });
  const pendingSavedSubmission = savedSubmission?.revision === consumedSubmissionRevision ? undefined : savedSubmission;
  const effectiveBaselineSignature = pendingSavedSubmission ? submittedSignature(pendingSavedSubmission.body) : baselineSignature;
  const canonicalSavedRecordReady = Boolean(pendingSavedSubmission?.canonicalReady && record);
  useEffect(() => {
    if (pendingSavedSubmission && !canonicalSavedRecordReady) return;
    if (incomingSignature === appliedIncomingSignature && !canonicalSavedRecordReady) return;
    if (currentSignature !== effectiveBaselineSignature) return;
    setAppliedIncomingSignature(incomingSignature);
    setStatus(record?.is_open ?? "营业"); setWash(record?.wash_count == null ? "" : String(record.wash_count));
    setWeatherValue(record?.weather ?? weather?.weather ?? ""); setWeatherEdited(record?.weather_edited ?? false); setActivity(record?.activity ?? "");
    setDirectTotal(loadedDirectTotal);
    setAmounts(loadedAmounts);
    setBaselineSignature(loadedSemanticSignature);
    if (canonicalSavedRecordReady) setConsumedSubmissionRevision(pendingSavedSubmission!.revision);
  }, [appliedIncomingSignature, canonicalSavedRecordReady, currentSignature, effectiveBaselineSignature, incomingSignature, loadedAmounts, loadedDirectTotal, loadedSemanticSignature, pendingSavedSubmission, record, weather?.weather]);
  useEffect(() => { onDirtyChange?.(currentSignature !== effectiveBaselineSignature); }, [currentSignature, effectiveBaselineSignature, onDirtyChange]);
  const includedAmounts = active.filter((category) => category.include_in_total).map((category) => parseWholeAmount(amounts[category.id] ?? "0"));
  const total = includedAmounts.every((result): result is { value: number } => "value" in result)
    ? includedAmounts.reduce<number | null>((sum, result) => {
      if (sum === null) return null;
      const next = sum + result.value;
      return Number.isSafeInteger(next) ? next : null;
    }, 0)
    : null;
  function changeStatus(next: LedgerStatus) {
    setStatus(next);
    if (next === "休息") setWash("0");
  }
  return <form aria-label="每日台账表单" className="grid min-w-0 gap-5" onSubmit={(event) => { event.preventDefault(); const items = active.map((category) => ({ category_id: category.id, result: status === "休息" ? { value: 0 } : parseWholeAmount(amounts[category.id] ?? "") })); const directResult = status === "休息" ? { value: 0 } : parseWholeAmount(directTotal); const invalid = (composed ? items.map((item) => item.result) : [directResult]).find((result): result is { error: string } => "error" in result); if (invalid) { setValidationError(invalid.error); return; } setValidationError(""); onSave({ is_open: status, daily_revenue: composed ? null : "value" in directResult ? directResult.value : 0, wash_count: status === "休息" ? 0 : wash === "" ? null : Number(wash), weather: weatherValue || null, weather_edited: weatherEdited, activity: activity.trim() || null, items: composed ? items.map((item) => ({ category_id: item.category_id, amount: "value" in item.result ? item.result.value : 0 })) : [] }); }}>
    <section role="group" aria-label="状态与天气" className="grid min-w-0 gap-4 md:grid-cols-2">
      <label className="grid min-w-0 gap-1.5 font-medium">状态<select aria-label="状态" value={status} onChange={(event) => changeStatus(event.target.value as LedgerStatus)} className={LEDGER_FIELD_CLASS}><option>营业</option><option>休息</option><option>天气停业</option></select></label>
      <div className="grid min-w-0 gap-1.5"><span className="font-medium">天气</span><Select value={weatherValue} onValueChange={(value) => { setWeatherValue(value); setWeatherEdited(true); }}><SelectTrigger aria-label="天气" className="h-11 text-base"><SelectValue placeholder="请选择天气">{weatherValue || undefined}</SelectValue></SelectTrigger><SelectContent>{MANUAL_RECORD_WEATHER_OPTIONS.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></div>
    </section>
    {composed ? <fieldset aria-label="收入项目" disabled={status === "休息"} className="grid min-w-0 gap-3"><legend className="font-semibold">收入项目</legend><div className="grid min-w-0 gap-4 md:grid-cols-2">{active.map((category) => <label className="grid min-w-0 gap-1.5 font-medium" key={category.id}>{category.name}<input aria-label={category.name} inputMode="numeric" type="text" value={amounts[category.id] ?? ""} onChange={(event) => setAmounts((old) => ({ ...old, [category.id]: event.target.value }))} className={LEDGER_FIELD_CLASS} /></label>)}</div></fieldset> : <label className="grid min-w-0 gap-1.5 font-medium">当日营业额<input aria-label="当日营业额" inputMode="numeric" type="text" disabled={status === "休息"} value={directTotal} onChange={(event) => setDirectTotal(event.target.value)} className={LEDGER_FIELD_CLASS} /></label>}
    <section className="min-w-0 overflow-hidden rounded-lg border bg-background"><button type="button" aria-controls="ledger-wash-activity" aria-expanded={washActivityOpen} onClick={() => setWashActivityOpen((open) => !open)} className="flex min-h-11 w-full items-center justify-between px-3 py-2 text-left font-medium outline-none transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">洗车数量 / 活动<span aria-hidden="true">{washActivityOpen ? "−" : "+"}</span></button>{washActivityOpen && <div id="ledger-wash-activity" className="grid min-w-0 gap-4 border-t p-4 md:grid-cols-2"><label className="grid min-w-0 gap-1.5 font-medium">洗车数量<input aria-label="洗车数量" type="number" min="0" disabled={status === "休息"} value={wash} onChange={(event) => setWash(event.target.value)} className={LEDGER_FIELD_CLASS} /></label><label className="grid min-w-0 gap-1.5 font-medium">活动<textarea aria-label="活动" value={activity} onChange={(event) => setActivity(event.target.value)} className={`${LEDGER_FIELD_CLASS} resize-y`} /></label></div>}</section>
    {validationError && <p role="alert" className="text-sm text-destructive">{validationError}</p>}
    <footer className="flex min-w-0 flex-col gap-4 rounded-lg bg-muted/50 p-4 sm:flex-row sm:items-center sm:justify-between">
      {composed && <p className="text-xl font-semibold tabular-nums">合计 {total === null ? "—" : formatWholeEuro(total)}</p>}
      <Button className="min-h-11 w-full px-6 text-base sm:ml-auto sm:w-auto sm:min-w-40" disabled={saving} type="submit">{submitLabel}</Button>
    </footer>
  </form>;
}
