import { useStore } from "@/stores/StoreProvider";

export function StorePicker({ showLabel = true }: { showLabel?: boolean }) {
  const { stores, selected, select, isLoading, error } = useStore();
  const currentName = selected ? `${selected.name}${selected.is_active === false ? "（已归档）" : ""}` : "";
  return <div className="grid min-w-0 max-w-full gap-1.5">
    <label className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
      <span className={showLabel ? "w-full text-xs font-medium opacity-80" : "sr-only"}>门店</span>
      <select aria-label="门店" title={currentName || "请选择门店"} value={selected?.id ?? ""} disabled={isLoading || Boolean(error) || !stores.length} onChange={(event) => select(Number(event.target.value))} className="h-11 min-w-0 max-w-full flex-1 truncate rounded-lg border bg-card px-2 text-base text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
        <option value="">{isLoading ? "正在加载门店…" : error ? "门店加载失败" : !stores.length ? "暂无可访问门店" : "请选择门店"}</option>{stores.map((store) => <option key={store.id} value={store.id}>{store.name}{store.is_active === false ? "（已归档）" : ""}</option>)}
      </select>
    </label>
    {isLoading && <p className="text-xs" role="status">正在加载门店…</p>}
    {!isLoading && !error && !stores.length && <p className="text-xs" role="status">暂无可访问门店</p>}
    {!isLoading && stores.length > 1 && !selected && <p className="text-xs" role="status">请先选择门店以查看数据。</p>}
  </div>;
}
