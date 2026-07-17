import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api, ApiError } from "@/api/client";
import type { AdminStore } from "@/api/types";
import { StoreLocationPicker } from "@/components/StoreLocationPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { MapLocation } from "@/maps/types";
import { accessibleStoresKey } from "@/stores/StoreProvider";

const storesKey = ["admin", "stores"] as const;

function ErrorMessage({ error, deletion = false }: { error: Error | null; deletion?: boolean }) {
  if (!error) return null;
  if (deletion && error instanceof ApiError && error.status === 409) {
    return <p role="alert" className="text-sm text-destructive">该门店已有经营或历史记录，只能归档门店。</p>;
  }
  return <p role="alert" className="text-sm text-destructive">{error instanceof ApiError ? error.detail : "请求失败"}</p>;
}

export function StoreSettingsPanel() {
  const queryClient = useQueryClient();
  const stores = useQuery({ queryKey: storesKey, queryFn: () => api<AdminStore[]>("/admin/stores") });
  const [selectedStoreId, setSelectedStoreId] = useState<number | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [createLocation, setCreateLocation] = useState<MapLocation | null>(null);
  const [editLocation, setEditLocation] = useState<MapLocation | null>(null);
  const visibleStores = stores.data?.filter((store) => store.is_active || showArchived) ?? [];
  useEffect(() => {
    if (visibleStores.some((store) => store.id === selectedStoreId)) return;
    setSelectedStoreId(visibleStores[0]?.id ?? null);
  }, [selectedStoreId, visibleStores]);
  const selectedStore = visibleStores.find((store) => store.id === selectedStoreId) ?? null;
  useEffect(() => {
    setEditLocation(selectedStore ? {
      label: selectedStore.address,
      latitude: Number(selectedStore.latitude),
      longitude: Number(selectedStore.longitude),
      timezone: selectedStore.timezone,
    } : null);
  }, [selectedStore?.id, selectedStore?.address, selectedStore?.latitude, selectedStore?.longitude, selectedStore?.timezone]);

  const invalidateStores = async () => {
    await queryClient.invalidateQueries({ queryKey: storesKey, exact: true });
    await queryClient.invalidateQueries({ queryKey: accessibleStoresKey });
  };
  const createStore = useMutation({
    mutationFn: (input: { name: string; address: string; latitude: number; longitude: number; timezone: string }) => api<AdminStore>("/admin/stores", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: invalidateStores,
  });
  const patchStore = useMutation({
    mutationFn: ({ storeId, body }: { storeId: number; body: Partial<Omit<AdminStore, "id">> }) => api<AdminStore>(`/admin/stores/${storeId}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: invalidateStores,
  });
  const deleteStore = useMutation({
    mutationFn: (storeId: number) => api<void>(`/admin/stores/${storeId}`, { method: "DELETE" }),
    onSuccess: invalidateStores,
  });

  function submitStore(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    if (!createLocation) return;
    createStore.mutate({
      name: String(data.get("name")),
      address: createLocation.label,
      latitude: createLocation.latitude,
      longitude: createLocation.longitude,
      timezone: createLocation.timezone,
    }, { onSuccess: () => { form.reset(); setCreateLocation(null); setShowCreate(false); } });
  }

  return <div className="space-y-4">
    <header aria-label="门店设置操作" className="flex flex-wrap items-end justify-between gap-3 rounded-lg border bg-card p-4">
      <div className="min-w-48 flex-1">
        <label htmlFor="current-store">当前门店</label>
        <select id="current-store" className="mt-1 h-9 w-full rounded-md border bg-background px-3" value={selectedStoreId ?? ""} onChange={(event) => setSelectedStoreId(Number(event.target.value))}>
          {visibleStores.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
        </select>
      </div>
      <Button type="button" variant="outline" onClick={() => setShowArchived((value) => !value)}>{showArchived ? "隐藏已归档门店" : "显示已归档门店"}</Button>
      <Button type="button" onClick={() => setShowCreate((value) => !value)}>{showCreate ? "取消新建" : "新建门店"}</Button>
    </header>

    <ErrorMessage error={stores.error} />
    <ErrorMessage error={createStore.error} />
    <ErrorMessage error={patchStore.error} />
    <ErrorMessage deletion error={deleteStore.variables === selectedStoreId ? deleteStore.error : null} />

    {showCreate && <form className="grid gap-3 rounded-lg border p-4 md:grid-cols-2" onSubmit={submitStore}>
      <div><label htmlFor="store-name">门店名称</label><Input id="store-name" name="name" required /></div>
      <div className="space-y-2"><p className="text-sm font-medium">门店位置</p><StoreLocationPicker value={createLocation} onConfirm={setCreateLocation} />{createLocation && <p className="text-sm text-muted-foreground">{createLocation.label}</p>}</div>
      <Button className="self-end" disabled={createStore.isPending || !createLocation} type="submit">{createStore.isPending ? "添加中…" : "添加门店"}</Button>
    </form>}

    <ul className="space-y-3">{stores.data?.filter((store) => store.id === selectedStoreId).map((store) => <li className="rounded-lg border p-4" key={store.id}>
      <form className="space-y-3" onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        patchStore.mutate({ storeId: store.id, body: {
          name: String(data.get("name")),
          ...(editLocation ? { address: editLocation.label, latitude: String(editLocation.latitude), longitude: String(editLocation.longitude), timezone: editLocation.timezone } : {}),
        } });
      }}>
        <div><label htmlFor={`store-name-${store.id}`}>门店名称 {store.name}</label><Input defaultValue={store.name} id={`store-name-${store.id}`} name="name" required /></div>
        <div className="space-y-2"><p className="text-sm font-medium">位置摘要</p><p className="text-sm text-muted-foreground">{editLocation?.label ?? store.address}</p><StoreLocationPicker value={editLocation} onConfirm={setEditLocation} /></div>
        <Button aria-label={`保存门店 ${store.name}`} disabled={patchStore.isPending} type="submit">保存</Button>
      </form>
      <section aria-label="危险操作" className="mt-6 border-t border-destructive/30 pt-4">
        <p className="mb-3 text-sm text-muted-foreground">归档会保留经营和历史数据，并从日常门店列表隐藏；只有从未使用的误建门店才能永久删除。</p>
        <div className="flex flex-wrap gap-2">
          <Button aria-label={`${store.is_active ? "归档" : "恢复归档"}门店 ${store.name}`} disabled={patchStore.isPending} type="button" variant="outline" onClick={() => patchStore.mutate({ storeId: store.id, body: { is_active: !store.is_active } })}>{store.is_active ? "归档门店" : "恢复归档"}</Button>
          <Button aria-label={`永久删除门店 ${store.name}`} disabled={deleteStore.isPending} type="button" variant="destructive" onClick={() => {
            if (window.confirm(`确定永久删除门店“${store.name}”吗？只有从未使用的门店可以删除。`)) deleteStore.mutate(store.id);
          }}>永久删除</Button>
        </div>
      </section>
    </li>)}</ul>
  </div>;
}
