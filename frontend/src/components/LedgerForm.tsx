import { useEffect, useMemo, useState } from "react";
import type { CategoryDescriptor, IncomeConfigResponse, LedgerBody, LedgerStatus, RecordSnapshot, WeatherResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { amountToCents, canonicalAmount, centsToMoney } from "@/lib/user-api";

export interface LedgerFormProps {
  categories: CategoryDescriptor[];
  config?: IncomeConfigResponse;
  record?: RecordSnapshot;
  weather?: WeatherResponse;
  onSave(body: LedgerBody): void;
  onDirtyChange?(dirty: boolean): void;
  saving?: boolean;
  submitLabel?: string;
  savedSubmission?: { revision: number; body: LedgerBody };
  recordRevision?: number;
}

function semanticAmount(value: string) {
  const result = canonicalAmount(value);
  return "value" in result ? result.value : `invalid:${value}`;
}

export function LedgerForm({ categories, config, record, weather, onSave, onDirtyChange, saving = false, submitLabel = "保存", savedSubmission, recordRevision }: LedgerFormProps) {
  const resolvedConfig = useMemo(() => config ?? ({
    store_id: record?.store_id ?? 0,
    version_id: record?.income_config_version_id ?? null,
    version: 0,
    enabled: record?.income_mode === "composed",
    formula: "",
    created_at: null,
    items: categories.map((category) => ({ ...category, category_id: category.id })),
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
      .filter((item) => item.is_active && item.category_id !== null)
      .map((item) => ({ id: item.category_id!, name: item.name, include_in_total: item.include_in_total, is_active: item.is_active, sort_order: item.sort_order }));
    return configured.sort((left, right) => left.sort_order - right.sort_order || left.id - right.id);
  }, [categories, composed, resolvedConfig.items, record]);
  const [status, setStatus] = useState<LedgerStatus>(record?.is_open ?? "营业");
  const [wash, setWash] = useState(record?.wash_count == null ? "" : String(record.wash_count));
  const [weatherValue, setWeatherValue] = useState(record?.weather ?? weather?.weather ?? "");
  const [weatherEdited, setWeatherEdited] = useState(record?.weather_edited ?? false);
  const [activity, setActivity] = useState(record?.activity ?? "");
  const [directTotal, setDirectTotal] = useState(record?.daily_revenue ?? "0");
  const loadedAmounts = useMemo(() => Object.fromEntries(active.map((category) => [category.id, record?.items.find((item) => item.category_id === category.id)?.amount ?? "0"])), [active, record]);
  const [amounts, setAmounts] = useState<Record<number, string>>(loadedAmounts);
  const [validationError, setValidationError] = useState("");
  const [weatherOpen, setWeatherOpen] = useState(false);
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
  const loadedSemanticSignature = semanticSignature({ status: record?.is_open ?? "营业", wash: record?.wash_count == null ? "" : String(record.wash_count), weatherValue: record?.weather ?? weather?.weather ?? "", weatherEdited: record?.weather_edited ?? false, activity: record?.activity ?? "", directTotal: record?.daily_revenue ?? "0", amounts: loadedAmounts });
  const [baselineSignature, setBaselineSignature] = useState(loadedSemanticSignature);
  const [appliedIncomingSignature, setAppliedIncomingSignature] = useState(incomingSignature);
  const [consumedSubmissionRevision, setConsumedSubmissionRevision] = useState<number | null>(null);
  const currentSignature = semanticSignature({ status, wash, weatherValue, weatherEdited, activity, directTotal, amounts });
  const pendingSavedSubmission = savedSubmission?.revision === consumedSubmissionRevision ? undefined : savedSubmission;
  const effectiveBaselineSignature = pendingSavedSubmission ? submittedSignature(pendingSavedSubmission.body) : baselineSignature;
  useEffect(() => {
    if (incomingSignature === appliedIncomingSignature) return;
    if (currentSignature !== effectiveBaselineSignature) return;
    setAppliedIncomingSignature(incomingSignature);
    setStatus(record?.is_open ?? "营业"); setWash(record?.wash_count == null ? "" : String(record.wash_count));
    setWeatherValue(record?.weather ?? weather?.weather ?? ""); setWeatherEdited(record?.weather_edited ?? false); setActivity(record?.activity ?? "");
    setDirectTotal(record?.daily_revenue ?? "0");
    setAmounts(loadedAmounts);
    setBaselineSignature(loadedSemanticSignature);
    if (pendingSavedSubmission && record) setConsumedSubmissionRevision(pendingSavedSubmission.revision);
  }, [appliedIncomingSignature, currentSignature, effectiveBaselineSignature, incomingSignature, loadedAmounts, loadedSemanticSignature, pendingSavedSubmission, record, weather?.weather]);
  useEffect(() => { onDirtyChange?.(currentSignature !== effectiveBaselineSignature); }, [currentSignature, effectiveBaselineSignature, onDirtyChange]);
  const includedCents = active.filter((category) => category.include_in_total).map((category) => amountToCents(amounts[category.id] ?? "0"));
  const total = includedCents.every((value): value is bigint => value !== null) ? includedCents.reduce<bigint>((sum, value) => sum + value, 0n) : null;
  function changeStatus(next: LedgerStatus) {
    setStatus(next);
    if (next === "休息") { setWash("0"); setAmounts(Object.fromEntries(active.map((category) => [category.id, "0"]))); }
  }
  return <form className="grid min-w-0 gap-3" onSubmit={(event) => { event.preventDefault(); const items = active.map((category) => ({ category_id: category.id, result: status === "休息" ? { value: "0.00" } : canonicalAmount(amounts[category.id] ?? "") })); const directResult = status === "休息" ? { value: "0.00" } : canonicalAmount(directTotal); const invalid = (composed ? items.map((item) => item.result) : [directResult]).find((result): result is { error: string } => "error" in result); if (invalid) { setValidationError(invalid.error); return; } setValidationError(""); onSave({ is_open: status, daily_revenue: composed ? null : "value" in directResult ? directResult.value : "0.00", config_version_id: composed ? record?.income_config_version_id ?? resolvedConfig.version_id : null, expected_version: record?.row_version ?? null, wash_count: status === "休息" ? 0 : wash === "" ? null : Number(wash), weather: weatherValue || null, weather_edited: weatherEdited, activity: activity.trim() || null, items: composed ? items.map((item) => ({ category_id: item.category_id, amount: "value" in item.result ? item.result.value : "0.00" })) : [] }); }}>
    <label>状态<select aria-label="状态" value={status} onChange={(event) => changeStatus(event.target.value as LedgerStatus)} className="w-full rounded border p-2"><option>营业</option><option>休息</option><option>天气停业</option></select></label>
    {composed ? <fieldset aria-label="收入项目" disabled={status === "休息"} className="grid gap-2 sm:grid-cols-2"><legend>收入项目</legend>{active.map((category) => <label key={category.id}>{category.name}<input aria-label={category.name} inputMode="decimal" value={amounts[category.id] ?? "0"} onChange={(event) => setAmounts((old) => ({ ...old, [category.id]: event.target.value }))} className="w-full rounded border p-2" /></label>)}</fieldset> : <label>当日营业额<input aria-label="当日营业额" inputMode="decimal" disabled={status === "休息"} value={directTotal} onChange={(event) => setDirectTotal(event.target.value)} className="w-full rounded border p-2" /></label>}
    {composed && <p className="text-xl font-semibold">合计 {total === null ? "—" : centsToMoney(total)}</p>}
    <section className="min-w-0 rounded-lg border"><button type="button" aria-controls="ledger-weather" aria-expanded={weatherOpen} onClick={() => setWeatherOpen((open) => !open)} className="flex min-h-11 w-full items-center justify-between px-3 py-2 text-left font-medium">天气<span aria-hidden="true">{weatherOpen ? "−" : "+"}</span></button>{weatherOpen && <div id="ledger-weather" className="border-t p-3"><label>天气<input aria-label="天气" value={weatherValue} onChange={(event) => { setWeatherValue(event.target.value); setWeatherEdited(true); }} className="w-full min-w-0 rounded border p-2" /></label></div>}</section>
    <section className="min-w-0 rounded-lg border"><button type="button" aria-controls="ledger-wash-activity" aria-expanded={washActivityOpen} onClick={() => setWashActivityOpen((open) => !open)} className="flex min-h-11 w-full items-center justify-between px-3 py-2 text-left font-medium">洗车数量 / 活动<span aria-hidden="true">{washActivityOpen ? "−" : "+"}</span></button>{washActivityOpen && <div id="ledger-wash-activity" className="grid min-w-0 gap-3 border-t p-3"><label>洗车数量<input aria-label="洗车数量" type="number" min="0" disabled={status === "休息"} value={wash} onChange={(event) => setWash(event.target.value)} className="w-full min-w-0 rounded border p-2" /></label><label>活动<textarea aria-label="活动" value={activity} onChange={(event) => setActivity(event.target.value)} className="w-full min-w-0 rounded border p-2" /></label></div>}</section>
    {validationError && <p role="alert">{validationError}</p>}<Button disabled={saving} type="submit">{submitLabel}</Button>
  </form>;
}
