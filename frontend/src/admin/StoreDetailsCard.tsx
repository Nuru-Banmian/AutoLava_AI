import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, ApiError } from "@/api/client";
import type { AdminStore } from "@/api/types";
import { StoreLocationPicker } from "@/components/StoreLocationPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { MapLocation } from "@/maps/types";
import { accessibleStoresKey } from "@/stores/StoreProvider";
import { useQueryClient } from "@tanstack/react-query";

const storesKey = ["admin", "stores"] as const;

export interface StoreDetailsCardProps {
  mode: "create" | "edit";
  store: AdminStore | null;
  onDirtyChange(dirty: boolean): void;
  onSaved(store: AdminStore): void;
  onDeleteRequested(deleteStore: () => void): void;
  onDeleted(storeId: number): void;
}

interface StoreDraft {
  name: string;
  location: MapLocation | null;
}

function draftFor(store: AdminStore | null): StoreDraft {
  return store ? {
    name: store.name,
    location: {
      label: store.address,
      latitude: Number(store.latitude),
      longitude: Number(store.longitude),
      timezone: store.timezone,
    },
  } : { name: "", location: null };
}

function sameDraft(left: StoreDraft, right: StoreDraft) {
  return left.name === right.name && JSON.stringify(left.location) === JSON.stringify(right.location);
}

function ErrorMessage({ error, deletion }: { error: unknown; deletion: boolean }) {
  if (!error) return null;
  if (deletion && error instanceof ApiError && error.status === 409) {
    return <p role="alert" className="text-sm text-destructive">该门店已有经营或历史记录，只能停用门店。</p>;
  }
  return <p role="alert" className="text-sm text-destructive">{error instanceof ApiError ? error.detail : "请求失败"}</p>;
}

export function StoreDetailsCard({ mode, store, onDirtyChange, onSaved, onDeleteRequested, onDeleted }: StoreDetailsCardProps) {
  const queryClient = useQueryClient();
  const initialRef = useRef(draftFor(store));
  const [name, setName] = useState(initialRef.current.name);
  const [location, setLocation] = useState<MapLocation | null>(initialRef.current.location);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [errorOperation, setErrorOperation] = useState<"save" | "delete" | null>(null);
  const mountedRef = useRef(false);
  const requestSequence = useRef(0);
  const dirty = !sameDraft({ name, location }, initialRef.current);
  const title = mode === "create" ? "新建门店" : "门店资料";

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestSequence.current += 1;
      onDirtyChange(false);
    };
  }, [onDirtyChange]);

  function beginRequest() {
    const requestId = ++requestSequence.current;
    setPending(true);
    setError(null);
    setErrorOperation(null);
    return requestId;
  }

  function isCurrent(requestId: number) {
    return mountedRef.current && requestSequence.current === requestId;
  }

  async function invalidateStores() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: storesKey, exact: true }),
      queryClient.invalidateQueries({ queryKey: accessibleStoresKey }),
    ]);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!location || (mode === "edit" && !store)) return;
    const requestId = beginRequest();
    const body = {
      name: name.trim(),
      address: location.label,
      latitude: mode === "create" ? location.latitude : String(location.latitude),
      longitude: mode === "create" ? location.longitude : String(location.longitude),
      timezone: location.timezone,
    };
    try {
      const saved = mode === "create"
        ? await api<AdminStore>("/admin/stores", { method: "POST", body: JSON.stringify(body) })
        : await api<AdminStore>(`/admin/stores/${store!.id}`, { method: "PATCH", body: JSON.stringify(body) });
      await invalidateStores();
      if (!isCurrent(requestId)) return;
      const next = draftFor(saved);
      initialRef.current = next;
      setName(next.name);
      setLocation(next.location);
      setPending(false);
      onDirtyChange(false);
      onSaved(saved);
    } catch (reason) {
      if (!isCurrent(requestId)) return;
      setPending(false);
      setErrorOperation("save");
      setError(reason);
    }
  }

  async function toggleActive() {
    if (!store) return;
    const requestId = beginRequest();
    try {
      await api<AdminStore>(`/admin/stores/${store.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !store.is_active }),
      });
      void invalidateStores();
      if (!isCurrent(requestId)) return;
      setPending(false);
    } catch (reason) {
      if (!isCurrent(requestId)) return;
      setPending(false);
      setErrorOperation("save");
      setError(reason);
    }
  }

  async function remove() {
    if (!store || !window.confirm(`确定永久删除门店“${store.name}”吗？只有从未使用的门店可以删除。`)) return;
    onDeleteRequested(() => void deleteStore());
  }

  async function deleteStore() {
    if (!store) return;
    const requestId = beginRequest();
    try {
      await api<void>(`/admin/stores/${store.id}`, { method: "DELETE" });
      void invalidateStores();
      if (!isCurrent(requestId)) return;
      setPending(false);
      onDirtyChange(false);
      onDeleted(store.id);
    } catch (reason) {
      if (!isCurrent(requestId)) return;
      setPending(false);
      setErrorOperation("delete");
      setError(reason);
    }
  }

  return <section className="space-y-4 rounded-lg border bg-card p-4" aria-labelledby="store-details-title">
    <h2 id="store-details-title" className="font-medium">{title}</h2>
    <ErrorMessage deletion={errorOperation === "delete"} error={error} />
    <fieldset className="space-y-4" disabled={pending}>
      <form className={mode === "edit" ? "grid gap-3 md:grid-cols-[minmax(10rem,1fr)_minmax(12rem,1.4fr)_auto_auto] md:items-end" : "grid gap-3 md:grid-cols-2"} onSubmit={(event) => void save(event)}>
        <div>
          <label htmlFor={`store-name-${mode}-${store?.id ?? "new"}`}>{mode === "edit" ? `门店名称 ${store?.name ?? ""}` : "门店名称"}</label>
          <Input
            id={`store-name-${mode}-${store?.id ?? "new"}`}
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        {mode === "edit" ? <>
          <div>
            <p className="text-sm font-medium">位置摘要</p>
            <p className="truncate text-sm text-muted-foreground">{location?.label ?? store?.address}</p>
          </div>
          <StoreLocationPicker buttonLabel="修改位置" onConfirm={setLocation} value={location} />
          <Button aria-busy={pending || undefined} disabled={!location || !name.trim()} type="submit">保存</Button>
        </> : <>
          <div className="space-y-2">
            <p className="text-sm font-medium">门店位置</p>
            <StoreLocationPicker onConfirm={setLocation} value={location} />
            {location && <p className="text-sm text-muted-foreground">{location.label}</p>}
          </div>
          <Button className="self-end" disabled={!location || !name.trim()} type="submit">{pending ? "添加中…" : "添加门店"}</Button>
        </>}
      </form>
      {mode === "edit" && store && <section aria-label="危险操作" className="border-t border-destructive/30 pt-4">
        <p className="mb-3 text-sm text-muted-foreground">有经营记录的门店只能停用；只有从未使用的误建门店才能永久删除。</p>
        <div className="flex flex-wrap gap-2">
          <Button aria-label={`${store.is_active ? "停用" : "启用"}门店 ${store.name}`} type="button" variant="outline" onClick={() => void toggleActive()}>{store.is_active ? "停用" : "启用"}</Button>
          <Button aria-label={`永久删除门店 ${store.name}`} type="button" variant="destructive" onClick={() => void remove()}>永久删除</Button>
        </div>
      </section>}
    </fieldset>
  </section>;
}
