import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, ApiError } from "@/api/client";
import type { components } from "@/api/generated";
import type { AdminStore } from "@/api/types";
import { currentSessionScope } from "@/auth/sessionScope";
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
  onDeleteFailed(): void;
  onDeleted(storeId: number): void;
}

interface StoreDraft {
  name: string;
  description: string;
  location: MapLocation | null;
}

function draftFor(store: AdminStore | null): StoreDraft {
  return store ? {
    name: store.name,
    description: store.description ?? "",
    location: {
      label: store.address,
      latitude: Number(store.latitude),
      longitude: Number(store.longitude),
      timezone: store.timezone,
    },
  } : { name: "", description: "", location: null };
}

function sameDraft(left: StoreDraft, right: StoreDraft) {
  return left.name === right.name && left.description === right.description
    && JSON.stringify(left.location) === JSON.stringify(right.location);
}

type DescriptionSnapshot = Pick<AdminStore, "description" | "description_revision">;

function descriptionConflict(error: unknown): DescriptionSnapshot | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const body = error.responseBody;
  if (!body || typeof body !== "object" || !("detail" in body)) return null;
  const detail = body.detail;
  if (!detail || typeof detail !== "object" || !("code" in detail)
    || detail.code !== "store_description_revision_conflict" || !("latest" in detail)) return null;
  const latest = detail.latest;
  if (!latest || typeof latest !== "object" || !("description" in latest)
    || typeof latest.description !== "string" || !("description_revision" in latest)
    || typeof latest.description_revision !== "number") return null;
  return { description: latest.description, description_revision: latest.description_revision };
}

function ErrorMessage({ error, deletion }: { error: unknown; deletion: boolean }) {
  if (!error) return null;
  if (deletion && error instanceof ApiError && error.status === 409) {
    return <p role="alert" className="text-sm leading-6 text-destructive [overflow-wrap:anywhere]">该门店已有经营或历史记录，只能停用门店。</p>;
  }
  return <p role="alert" className="text-sm leading-6 text-destructive [overflow-wrap:anywhere]">{error instanceof ApiError ? error.detail : "请求失败"}</p>;
}

export function StoreDetailsCard({ mode, store, onDirtyChange, onSaved, onDeleteRequested, onDeleteFailed, onDeleted }: StoreDetailsCardProps) {
  const queryClient = useQueryClient();
  const initialRef = useRef(draftFor(store));
  const [name, setName] = useState(initialRef.current.name);
  const [description, setDescription] = useState(initialRef.current.description);
  const descriptionRevision = useRef(store?.description_revision ?? 1);
  const [conflict, setConflict] = useState<DescriptionSnapshot | null>(null);
  const [location, setLocation] = useState<MapLocation | null>(initialRef.current.location);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [errorOperation, setErrorOperation] = useState<"save" | "delete" | null>(null);
  const mountedRef = useRef(false);
  const requestSequence = useRef(0);
  const dirty = !sameDraft({ name, description, location }, initialRef.current);
  const descriptionLength = Array.from(description).length;
  const canSave = Boolean(location && name.trim() && descriptionLength <= 3000 && !conflict);
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
    if (!canSave || !location || (mode === "edit" && !store)) return;
    const requestId = beginRequest();
    const sessionScope = currentSessionScope();
    const body = {
      name: name.trim(),
      address: location.label,
      latitude: mode === "create" ? location.latitude : String(location.latitude),
      longitude: mode === "create" ? location.longitude : String(location.longitude),
      timezone: location.timezone,
    } satisfies Omit<components["schemas"]["StoreCreate"], "wash_count_enabled" | "description">;
    try {
      const saved = mode === "create"
        ? await api<AdminStore>("/admin/stores", { method: "POST", body: JSON.stringify({ ...body, description }) })
        : await api<AdminStore>(`/admin/stores/${store!.id}`, { method: "PATCH", body: JSON.stringify({
          ...body,
          ...(description !== initialRef.current.description ? {
            description, expected_description_revision: descriptionRevision.current,
          } : {}),
        } satisfies components["schemas"]["StorePatch"]) });
      if (sessionScope !== currentSessionScope()) return;
      await invalidateStores();
      if (!isCurrent(requestId)) return;
      const next = draftFor(saved);
      initialRef.current = next;
      setName(next.name);
      setDescription(next.description);
      descriptionRevision.current = saved.description_revision ?? 1;
      setConflict(null);
      setLocation(next.location);
      setPending(false);
      onDirtyChange(false);
      onSaved(saved);
    } catch (reason) {
      if (!isCurrent(requestId)) return;
      setPending(false);
      setErrorOperation("save");
      setError(reason);
      setConflict(descriptionConflict(reason));
    }
  }

  async function toggleActive() {
    if (!store) return;
    const requestId = beginRequest();
    try {
      await api<AdminStore>(`/admin/stores/${store.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !store.is_active } satisfies components["schemas"]["StorePatch"]),
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

  async function toggleStoreSetting(
    changes: Partial<Pick<AdminStore, "company_settlement_enabled" | "wash_count_enabled">>,
  ) {
    if (!store) return;
    const requestId = beginRequest();
    try {
      const saved = await api<AdminStore>(`/admin/stores/${store.id}`, {
        method: "PATCH",
        body: JSON.stringify(changes),
      });
      await invalidateStores();
      if (!isCurrent(requestId)) return;
      setPending(false);
      if (!dirty) onSaved(saved);
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
      onDeleteFailed();
    }
  }

  return <section className="min-w-0 space-y-4 rounded-xl border border-border bg-card p-4 shadow-sm [overflow-wrap:anywhere] sm:p-5" aria-labelledby="store-details-title">
    <h2 id="store-details-title" className="text-lg font-semibold">{title}</h2>
    <ErrorMessage deletion={errorOperation === "delete"} error={error} />
    <fieldset className="min-w-0 space-y-4" disabled={pending}>
      <form className="grid min-w-0 gap-4 sm:grid-cols-2 sm:items-end" onSubmit={(event) => void save(event)}>
        <div className="min-w-0 space-y-2 sm:col-span-2">
          <label className="block text-sm font-medium" htmlFor={`store-description-${mode}-${store?.id ?? "new"}`}>门店描述</label>
          <textarea
            id={`store-description-${mode}-${store?.id ?? "new"}`}
            aria-describedby="store-description-help store-description-count"
            aria-invalid={descriptionLength > 3000 || undefined}
            className="min-h-32 w-full min-w-0 resize-y rounded-lg border border-input bg-card px-3 py-2 text-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            rows={5}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
          <p id="store-description-help" className="text-sm leading-6 text-muted-foreground">可填写行业、主营业务、客户特点等稳定背景，例如烘焙、零售、维修或洗车。支持多行纯文本；留空或仅空白表示清空。</p>
          <p id="store-description-count" role={descriptionLength > 3000 ? "alert" : undefined} className={descriptionLength > 3000 ? "text-sm text-destructive" : "text-sm text-muted-foreground"}>{descriptionLength} / 3000 字符{descriptionLength > 3000 ? "，请缩短描述" : ""}</p>
          <Button disabled={!description} onClick={() => setDescription("")} type="button" variant="outline">清空描述</Button>
          {conflict && <section aria-label="描述冲突核对" className="min-w-0 space-y-3 rounded-lg border p-3">
            <p className="text-sm font-medium">最新已保存描述（版本 {conflict.description_revision}）</p>
            <p className="whitespace-pre-wrap text-sm [overflow-wrap:anywhere]">{conflict.description || "（空描述）"}</p>
            <p className="text-sm text-muted-foreground">你的草稿仍保留在输入框中。请核对后选择，再点击保存。</p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={() => {
                descriptionRevision.current = conflict.description_revision;
                initialRef.current = { ...initialRef.current, description: conflict.description };
                setConflict(null);
                setError(null);
              }}>已核对，保留草稿</Button>
              <Button type="button" variant="outline" onClick={() => {
                descriptionRevision.current = conflict.description_revision;
                initialRef.current = { ...initialRef.current, description: conflict.description };
                setDescription(conflict.description);
                setConflict(null);
                setError(null);
              }}>采用最新描述</Button>
            </div>
          </section>}
        </div>
        <div className="min-w-0 space-y-2">
          <label className="block text-sm font-medium leading-6" htmlFor={`store-name-${mode}-${store?.id ?? "new"}`}>{mode === "edit" ? `门店名称 ${store?.name ?? ""}` : "门店名称"}</label>
          <Input
            id={`store-name-${mode}-${store?.id ?? "new"}`}
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        {mode === "edit" ? <>
          <div className="min-w-0 space-y-2">
            <p className="text-sm font-medium">位置摘要</p>
            <p className="text-sm leading-6 text-muted-foreground">{location?.label ?? store?.address}</p>
          </div>
          <StoreLocationPicker buttonLabel="修改位置" onConfirm={setLocation} value={location} />
          <Button aria-busy={pending || undefined} disabled={!canSave} type="submit">保存</Button>
        </> : <>
          <div className="min-w-0 space-y-2">
            <p className="text-sm font-medium">门店位置</p>
            <StoreLocationPicker onConfirm={setLocation} value={location} />
            {location && <p className="text-sm leading-6 text-muted-foreground">{location.label}</p>}
          </div>
          <Button className="self-end" disabled={!canSave} type="submit">{pending ? "添加中…" : "添加门店"}</Button>
        </>}
      </form>
      {mode === "edit" && store && <section aria-labelledby={`settlement-setting-${store.id}`} className="border-t pt-4">
        <h3 id={`settlement-setting-${store.id}`} className="font-medium">公司结算</h3>
        <label className="mt-2 flex min-h-11 cursor-pointer items-start gap-3 py-2">
          <input
            checked={store.company_settlement_enabled ?? false}
            className="mt-1 size-4 shrink-0 accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            onChange={() => void toggleStoreSetting({
              company_settlement_enabled: !store.company_settlement_enabled,
            })}
            type="checkbox"
          />
          <span className="min-w-0">
            <span className="block text-sm font-medium">为此门店启用公司结算</span>
            <span className="mt-1 block text-sm leading-6 text-muted-foreground">关闭后保留既有历史，但不再允许新的公司结算业务操作。</span>
          </span>
        </label>
      </section>}
      {mode === "edit" && store && <section aria-labelledby={`wash-count-setting-${store.id}`} className="border-t pt-4">
        <h3 id={`wash-count-setting-${store.id}`} className="font-medium">记录洗车数量</h3>
        <label className="mt-2 flex min-h-11 cursor-pointer items-start gap-3 py-2">
          <input
            checked={store.wash_count_enabled ?? true}
            className="mt-1 size-4 shrink-0 accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            onChange={() => void toggleStoreSetting({
              wash_count_enabled: !(store.wash_count_enabled ?? true),
            })}
            type="checkbox"
          />
          <span className="min-w-0">
            <span className="block text-sm font-medium">为此门店记录洗车数量</span>
            <span className="mt-1 block text-sm leading-6 text-muted-foreground">关闭后保留历史洗车数量，但记账时不再录入；重新开启即可恢复使用。</span>
          </span>
        </label>
      </section>}
      {mode === "edit" && store && <section aria-label="危险操作" className="border-t border-destructive/30 pt-4">
        <p className="mb-3 text-sm leading-6 text-muted-foreground">有经营记录的门店只能停用；只有从未使用的误建门店才能永久删除。</p>
        <div className="flex flex-wrap gap-2">
          <Button aria-label={`${store.is_active ? "停用" : "启用"}门店 ${store.name}`} type="button" variant="outline" onClick={() => void toggleActive()}>{store.is_active ? "停用" : "启用"}</Button>
          <Button aria-label={`永久删除门店 ${store.name}`} type="button" variant="destructive" onClick={() => void remove()}>永久删除</Button>
        </div>
      </section>}
    </fieldset>
  </section>;
}
