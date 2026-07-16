import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";

import { api, ApiError } from "@/api/client";
import type { AdminStore } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { accessibleStoresKey } from "@/stores/StoreProvider";

const storesKey = ["admin", "stores"] as const;
function ErrorMessage({ error }: { error: Error | null }) { if (!error) return null; return <p role="alert" className="text-sm text-destructive">{error instanceof ApiError ? error.detail : "请求失败"}</p>; }

export function StoreSettingsPanel() {
  const queryClient = useQueryClient();
  const stores = useQuery({ queryKey: storesKey, queryFn: () => api<AdminStore[]>("/admin/stores") });
  const invalidateStores = async () => { await queryClient.invalidateQueries({ queryKey: storesKey, exact: true }); await queryClient.invalidateQueries({ queryKey: accessibleStoresKey }); };
  const createStore = useMutation({ mutationFn: (input: { name: string; address: string; latitude: number; longitude: number; timezone: string }) => api<AdminStore>("/admin/stores", { method: "POST", body: JSON.stringify(input) }), onSuccess: invalidateStores });
  const patchStore = useMutation({ mutationFn: ({ storeId, body }: { storeId: number; body: Partial<Omit<AdminStore, "id">> }) => api<AdminStore>(`/admin/stores/${storeId}`, { method: "PATCH", body: JSON.stringify(body) }), onSuccess: invalidateStores });
  function submitStore(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); createStore.mutate({ name: String(data.get("name")), address: String(data.get("address")), latitude: Number(data.get("latitude")), longitude: Number(data.get("longitude")), timezone: String(data.get("timezone")) }, { onSuccess: () => form.reset() }); }

  return <>
    <ErrorMessage error={stores.error} /><ErrorMessage error={createStore.error} /><ErrorMessage error={patchStore.error} />
    <form className="grid gap-3 rounded-lg border p-4 md:grid-cols-3" onSubmit={submitStore}>
      <div><label htmlFor="store-name">门店名称</label><Input id="store-name" name="name" required /></div><div><label htmlFor="store-address">地址</label><Input id="store-address" name="address" required /></div><div><label htmlFor="store-latitude">纬度</label><Input id="store-latitude" name="latitude" required type="number" step="any" /></div><div><label htmlFor="store-longitude">经度</label><Input id="store-longitude" name="longitude" required type="number" step="any" /></div><div><label htmlFor="store-timezone">时区</label><Input defaultValue="Europe/Rome" id="store-timezone" name="timezone" required /></div><Button className="self-end" disabled={createStore.isPending} type="submit">{createStore.isPending ? "添加中…" : "添加门店"}</Button>
    </form>
    <ul className="space-y-3">{stores.data?.map((store) => <li className="rounded-lg border p-3" key={store.id}><form className="grid gap-2 md:grid-cols-3" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); patchStore.mutate({ storeId: store.id, body: { name: String(data.get("name")), address: String(data.get("address")), latitude: String(data.get("latitude")), longitude: String(data.get("longitude")), timezone: String(data.get("timezone")) } }); }}>
      <div><label htmlFor={`store-name-${store.id}`}>门店名称 {store.name}</label><Input defaultValue={store.name} id={`store-name-${store.id}`} name="name" required /></div><div><label htmlFor={`store-address-${store.id}`}>地址 {store.name}</label><Input defaultValue={store.address} id={`store-address-${store.id}`} name="address" required /></div><div><label htmlFor={`store-lat-${store.id}`}>纬度 {store.name}</label><Input defaultValue={store.latitude} id={`store-lat-${store.id}`} name="latitude" required type="number" step="any" /></div><div><label htmlFor={`store-lon-${store.id}`}>经度 {store.name}</label><Input defaultValue={store.longitude} id={`store-lon-${store.id}`} name="longitude" required type="number" step="any" /></div><div><label htmlFor={`store-tz-${store.id}`}>时区 {store.name}</label><Input defaultValue={store.timezone} id={`store-tz-${store.id}`} name="timezone" required /></div><div className="flex items-end gap-2"><Button aria-label={`保存门店 ${store.name}`} disabled={patchStore.isPending} type="submit">保存</Button><Button aria-label={`${store.is_active ? "停用" : "启用"}门店 ${store.name}`} disabled={patchStore.isPending} type="button" variant="outline" onClick={() => patchStore.mutate({ storeId: store.id, body: { is_active: !store.is_active } })}>{store.is_active ? "停用" : "启用"}</Button></div>
    </form></li>)}</ul>
  </>;
}
