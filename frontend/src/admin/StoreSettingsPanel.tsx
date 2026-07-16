import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api, ApiError } from "@/api/client";
import type { AdminStore } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { accessibleStoresKey } from "@/stores/StoreProvider";

const storesKey = ["admin", "stores"] as const;

function ErrorMessage({ error, deletion = false }: { error: Error | null; deletion?: boolean }) {
  if (!error) return null;
  if (deletion && error instanceof ApiError && error.status === 409) {
    return <p role="alert" className="text-sm text-destructive">该门店已有经营或历史记录，只能停用门店。</p>;
  }
  return <p role="alert" className="text-sm text-destructive">{error instanceof ApiError ? error.detail : "请求失败"}</p>;
}

export function StoreSettingsPanel() {
  const queryClient = useQueryClient();
  const stores = useQuery({ queryKey: storesKey, queryFn: () => api<AdminStore[]>("/admin/stores") });
  const [selectedStoreId, setSelectedStoreId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(true);
  useEffect(() => {
    if (stores.data?.some((store) => store.id === selectedStoreId)) return;
    setSelectedStoreId(stores.data?.[0]?.id ?? null);
  }, [selectedStoreId, stores.data]);

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
    createStore.mutate({
      name: String(data.get("name")),
      address: String(data.get("address")),
      latitude: Number(data.get("latitude")),
      longitude: Number(data.get("longitude")),
      timezone: String(data.get("timezone")),
    }, { onSuccess: () => form.reset() });
  }

  return <div className="space-y-4">
    <header aria-label="门店设置操作" className="flex flex-wrap items-end justify-between gap-3 rounded-lg border bg-card p-4">
      <div className="min-w-48 flex-1">
        <label htmlFor="current-store">当前门店</label>
        <select id="current-store" className="mt-1 h-9 w-full rounded-md border bg-background px-3" value={selectedStoreId ?? ""} onChange={(event) => setSelectedStoreId(Number(event.target.value))}>
          {stores.data?.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
        </select>
      </div>
      <Button type="button" onClick={() => setShowCreate((value) => !value)}>新建门店</Button>
    </header>

    <ErrorMessage error={stores.error} />
    <ErrorMessage error={createStore.error} />
    <ErrorMessage error={patchStore.error} />
    <ErrorMessage deletion error={deleteStore.error} />

    {showCreate && <form className="grid gap-3 rounded-lg border p-4 md:grid-cols-3" onSubmit={submitStore}>
      <div><label htmlFor="store-name">门店名称</label><Input id="store-name" name="name" required /></div>
      <div><label htmlFor="store-address">地址</label><Input id="store-address" name="address" required /></div>
      <div><label htmlFor="store-latitude">纬度</label><Input id="store-latitude" name="latitude" required type="number" step="any" /></div>
      <div><label htmlFor="store-longitude">经度</label><Input id="store-longitude" name="longitude" required type="number" step="any" /></div>
      <div><label htmlFor="store-timezone">时区</label><Input defaultValue="Europe/Rome" id="store-timezone" name="timezone" required /></div>
      <Button className="self-end" disabled={createStore.isPending} type="submit">{createStore.isPending ? "添加中…" : "添加门店"}</Button>
    </form>}

    <ul className="space-y-3">{stores.data?.filter((store) => store.id === selectedStoreId).map((store) => <li className="rounded-lg border p-4" key={store.id}>
      <form className="space-y-3" onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        patchStore.mutate({ storeId: store.id, body: { name: String(data.get("name")) } });
      }}>
        <div><label htmlFor={`store-name-${store.id}`}>门店名称 {store.name}</label><Input defaultValue={store.name} id={`store-name-${store.id}`} name="name" required /></div>
        <div><p className="text-sm font-medium">位置摘要</p><p className="text-sm text-muted-foreground">{store.address}</p></div>
        <Button aria-label={`保存门店 ${store.name}`} disabled={patchStore.isPending} type="submit">保存</Button>
      </form>
      <section aria-label="危险操作" className="mt-6 border-t border-destructive/30 pt-4">
        <p className="mb-3 text-sm text-muted-foreground">有经营记录的门店只能停用；只有从未使用的误建门店才能永久删除。</p>
        <div className="flex flex-wrap gap-2">
          <Button aria-label={`${store.is_active ? "停用" : "启用"}门店 ${store.name}`} disabled={patchStore.isPending} type="button" variant="outline" onClick={() => patchStore.mutate({ storeId: store.id, body: { is_active: !store.is_active } })}>{store.is_active ? "停用" : "启用"}</Button>
          <Button aria-label={`永久删除门店 ${store.name}`} disabled={deleteStore.isPending} type="button" variant="destructive" onClick={() => {
            if (window.confirm(`确定永久删除门店“${store.name}”吗？只有从未使用的门店可以删除。`)) deleteStore.mutate(store.id);
          }}>永久删除</Button>
        </div>
      </section>
    </li>)}</ul>
  </div>;
}
