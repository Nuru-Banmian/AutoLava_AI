import { useEffect, useMemo, useState } from "react";
import type { CategoryDescriptor, LedgerBody, LedgerStatus, RecordSnapshot, WeatherResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { amountToCents, centsToMoney } from "@/lib/user-api";

export function LedgerForm({ categories, record, weather, onSave, saving = false }: { categories: CategoryDescriptor[]; record?: RecordSnapshot; weather?: WeatherResponse; onSave(body: LedgerBody): void; saving?: boolean }) {
  const active = useMemo(() => categories.filter((category) => category.is_active || record?.items.some((item) => item.category_id === category.id)), [categories, record]);
  const [status, setStatus] = useState<LedgerStatus>(record?.is_open ?? "营业");
  const [wash, setWash] = useState(record?.wash_count == null ? "" : String(record.wash_count));
  const [weatherValue, setWeatherValue] = useState(record?.weather ?? weather?.weather ?? "");
  const [weatherEdited, setWeatherEdited] = useState(record?.weather_edited ?? false);
  const [activity, setActivity] = useState(record?.activity ?? "");
  const [amounts, setAmounts] = useState<Record<number, string>>({});
  useEffect(() => {
    setStatus(record?.is_open ?? "营业"); setWash(record?.wash_count == null ? "" : String(record.wash_count));
    setWeatherValue(record?.weather ?? ""); setWeatherEdited(record?.weather_edited ?? false); setActivity(record?.activity ?? "");
    setAmounts(Object.fromEntries(active.map((category) => [category.id, record?.items.find((item) => item.category_id === category.id)?.amount ?? "0"])));
  }, [record?.id, active.map((c) => c.id).join(",")]);
  useEffect(() => { if (!record && !weatherEdited && weather?.weather) setWeatherValue(weather.weather); }, [weather?.weather, record?.id, weatherEdited]);
  const total = active.filter((category) => category.include_in_total).reduce((sum, category) => sum + amountToCents(amounts[category.id] ?? "0"), 0n);
  function changeStatus(next: LedgerStatus) {
    setStatus(next);
    if (next === "休息") { setWash("0"); setAmounts(Object.fromEntries(active.map((category) => [category.id, "0"]))); }
  }
  return <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); onSave({ is_open: status, wash_count: status === "休息" ? 0 : wash === "" ? null : Number(wash), weather: weatherValue || null, weather_edited: weatherEdited, activity: activity.trim() || null, items: active.filter((c) => c.is_active || record?.items.some((i) => i.category_id === c.id)).map((category) => ({ category_id: category.id, amount: status === "休息" ? "0" : amounts[category.id] || "0" })) }); }}>
    <label>状态<select aria-label="状态" value={status} onChange={(event) => changeStatus(event.target.value as LedgerStatus)} className="w-full rounded border p-2"><option>营业</option><option>休息</option><option>天气停业</option></select></label>
    <label>洗车数量<input aria-label="洗车数量" type="number" min="0" disabled={status === "休息"} value={wash} onChange={(event) => setWash(event.target.value)} className="w-full rounded border p-2" /></label>
    <label>天气<input aria-label="天气" value={weatherValue} onChange={(event) => { setWeatherValue(event.target.value); setWeatherEdited(true); }} className="w-full rounded border p-2" /></label>
    <label>活动<textarea aria-label="活动" value={activity} onChange={(event) => setActivity(event.target.value)} className="w-full rounded border p-2" /></label>
    <fieldset disabled={status === "休息"} className="grid gap-2 sm:grid-cols-2"><legend>分类金额</legend>{active.map((category) => <label key={category.id}>{category.name}<input aria-label={category.name} inputMode="decimal" value={amounts[category.id] ?? "0"} onChange={(event) => setAmounts((old) => ({ ...old, [category.id]: event.target.value }))} className="w-full rounded border p-2" /></label>)}</fieldset>
    <p className="text-xl font-semibold">合计 {centsToMoney(total)}</p><Button disabled={saving} type="submit">保存</Button>
  </form>;
}
