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
  saving?: boolean;
}

export function LedgerForm({ categories, config, record, weather, onSave, saving = false }: LedgerFormProps) {
  const resolvedConfig = useMemo(() => config ?? ({
    store_id: record?.store_id ?? 0,
    version_id: record?.income_config_version_id ?? null,
    version: 0,
    enabled: Boolean(record && (record.income_config_version_id !== null || record.items.length > 0)),
    formula: "",
    items: categories.map((category) => ({ ...category, category_id: category.id })),
  }), [categories, config, record]);
  const composed = record ? record.income_config_version_id !== null || record.items.length > 0 : resolvedConfig.enabled;
  const active = useMemo(() => {
    const catalog = new Map(categories.map((category) => [category.id, category]));
    if (record && composed) {
      return record.items.map((item) => {
        const snapshot = item as typeof item & { category_name?: string; include_in_total?: boolean; sort_order?: number };
        const fallback = catalog.get(item.category_id);
        return {
          id: item.category_id,
          name: snapshot.category_name ?? fallback?.name ?? "历史收入项目",
          include_in_total: snapshot.include_in_total ?? fallback?.include_in_total ?? true,
          is_active: true,
          sort_order: snapshot.sort_order ?? fallback?.sort_order ?? 0,
        };
      }).sort((left, right) => left.sort_order - right.sort_order || left.id - right.id);
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
  const [amounts, setAmounts] = useState<Record<number, string>>({});
  const [validationError, setValidationError] = useState("");
  useEffect(() => {
    setStatus(record?.is_open ?? "营业"); setWash(record?.wash_count == null ? "" : String(record.wash_count));
    setWeatherValue(record?.weather ?? ""); setWeatherEdited(record?.weather_edited ?? false); setActivity(record?.activity ?? "");
    setDirectTotal(record?.daily_revenue ?? "0");
    setAmounts(Object.fromEntries(active.map((category) => [category.id, record?.items.find((item) => item.category_id === category.id)?.amount ?? "0"])));
  }, [record?.id, active.map((c) => c.id).join(",")]);
  useEffect(() => { if (!record && !weatherEdited && weather?.weather) setWeatherValue(weather.weather); }, [weather?.weather, record?.id, weatherEdited]);
  const includedCents = active.filter((category) => category.include_in_total).map((category) => amountToCents(amounts[category.id] ?? "0"));
  const total = includedCents.every((value): value is bigint => value !== null) ? includedCents.reduce<bigint>((sum, value) => sum + value, 0n) : null;
  function changeStatus(next: LedgerStatus) {
    setStatus(next);
    if (next === "休息") { setWash("0"); setAmounts(Object.fromEntries(active.map((category) => [category.id, "0"]))); }
  }
  return <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); const items = active.map((category) => ({ category_id: category.id, result: status === "休息" ? { value: "0.00" } : canonicalAmount(amounts[category.id] ?? "") })); const directResult = status === "休息" ? { value: "0.00" } : canonicalAmount(directTotal); const invalid = (composed ? items.map((item) => item.result) : [directResult]).find((result): result is { error: string } => "error" in result); if (invalid) { setValidationError(invalid.error); return; } setValidationError(""); onSave({ is_open: status, daily_revenue: composed ? null : "value" in directResult ? directResult.value : "0.00", config_version_id: composed ? record?.income_config_version_id ?? resolvedConfig.version_id : null, expected_version: record?.row_version ?? null, wash_count: status === "休息" ? 0 : wash === "" ? null : Number(wash), weather: weatherValue || null, weather_edited: weatherEdited, activity: activity.trim() || null, items: composed ? items.map((item) => ({ category_id: item.category_id, amount: "value" in item.result ? item.result.value : "0.00" })) : [] }); }}>
    <label>状态<select aria-label="状态" value={status} onChange={(event) => changeStatus(event.target.value as LedgerStatus)} className="w-full rounded border p-2"><option>营业</option><option>休息</option><option>天气停业</option></select></label>
    <label>洗车数量<input aria-label="洗车数量" type="number" min="0" disabled={status === "休息"} value={wash} onChange={(event) => setWash(event.target.value)} className="w-full rounded border p-2" /></label>
    <label>天气<input aria-label="天气" value={weatherValue} onChange={(event) => { setWeatherValue(event.target.value); setWeatherEdited(true); }} className="w-full rounded border p-2" /></label>
    <label>活动<textarea aria-label="活动" value={activity} onChange={(event) => setActivity(event.target.value)} className="w-full rounded border p-2" /></label>
    {composed ? <fieldset aria-label="收入项目" disabled={status === "休息"} className="grid gap-2 sm:grid-cols-2"><legend>收入项目</legend>{active.map((category) => <label key={category.id}>{category.name}<input aria-label={category.name} inputMode="decimal" value={amounts[category.id] ?? "0"} onChange={(event) => setAmounts((old) => ({ ...old, [category.id]: event.target.value }))} className="w-full rounded border p-2" /></label>)}</fieldset> : <label>当日营业额<input aria-label="当日营业额" inputMode="decimal" disabled={status === "休息"} value={directTotal} onChange={(event) => setDirectTotal(event.target.value)} className="w-full rounded border p-2" /></label>}
    {composed && <p className="text-xl font-semibold">合计 {total === null ? "—" : centsToMoney(total)}</p>}{validationError && <p role="alert">{validationError}</p>}<Button disabled={saving} type="submit">保存</Button>
  </form>;
}
