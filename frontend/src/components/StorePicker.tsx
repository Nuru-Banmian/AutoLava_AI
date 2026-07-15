import { useStore } from "@/stores/StoreProvider";

export function StorePicker() {
  const { stores, selected, select, isLoading, error } = useStore();
  return <div className="min-w-0 max-w-full">
    <label className="flex min-w-0 max-w-full items-center gap-2">门店
      <select aria-label="门店" value={selected?.id ?? ""} disabled={isLoading || Boolean(error) || !stores.length} onChange={(event) => select(Number(event.target.value))} className="min-w-0 max-w-full flex-1 rounded border p-2">
        <option value="">请选择门店</option>{stores.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
      </select>
    </label>
    {!isLoading && stores.length > 1 && !selected && <p role="status">请先选择门店以查看数据。</p>}
  </div>;
}
