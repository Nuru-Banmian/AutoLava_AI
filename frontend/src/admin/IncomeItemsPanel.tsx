import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, friendlyApiError } from "@/api/client";
import type { AdminStore, IncomeCategory, IncomeConfigResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { invalidateUserData } from "@/lib/user-api";

const storesKey = ["admin", "stores"] as const;
const configKey = (storeId: number) => ["income-config", storeId, "current"] as const;
const categoriesKey = (storeId: number) => ["admin", "income-categories", storeId] as const;

type CategoryWithArchive = IncomeCategory & { archived_at: string | null };
type DraftItem = {
  key: string;
  category_id: number | null;
  name: string;
  include_in_total: boolean;
  is_active: boolean;
  sort_order: number;
};

let nextDraftKey = 0;

function configItems(config: IncomeConfigResponse): DraftItem[] {
  return [...config.items]
    .sort((left, right) => left.sort_order - right.sort_order)
    .map((item, sort_order) => ({
      key: item.category_id === null ? `snapshot-${item.id}` : `category-${item.category_id}`,
      category_id: item.category_id,
      name: item.name,
      include_in_total: item.include_in_total,
      is_active: item.is_active,
      sort_order,
    }));
}

function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null;
  return <p role="alert" className="text-sm text-destructive">{friendlyApiError(error, "请求失败，请稍后重试")}</p>;
}

export function IncomeItemsPanel({ selectedStoreId, onSelectedStoreChange }: {
  selectedStoreId: number | null;
  onSelectedStoreChange: (storeId: number | null) => void;
}) {
  const queryClient = useQueryClient();
  const [items, setItems] = useState<DraftItem[]>([]);
  const [draftStoreId, setDraftStoreId] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const stores = useQuery({ queryKey: storesKey, queryFn: () => api<AdminStore[]>("/admin/stores") });
  const currentConfig = useQuery({
    queryKey: configKey(selectedStoreId ?? 0),
    queryFn: () => api<IncomeConfigResponse>(`/income-config/${selectedStoreId}/current`),
    enabled: selectedStoreId !== null,
  });
  const categories = useQuery({
    queryKey: categoriesKey(selectedStoreId ?? 0),
    queryFn: () => api<CategoryWithArchive[]>(`/admin/income-categories?store_id=${selectedStoreId}`),
    enabled: selectedStoreId !== null,
  });

  useEffect(() => {
    setItems([]);
    setDraftStoreId(null);
  }, [selectedStoreId]);

  useEffect(() => {
    if (currentConfig.data && currentConfig.data.store_id === selectedStoreId) {
      setItems(configItems(currentConfig.data));
      setDraftStoreId(currentConfig.data.store_id);
    }
  }, [currentConfig.data, selectedStoreId]);

  async function refreshStore(storeId: number) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: configKey(storeId), exact: true }),
      queryClient.invalidateQueries({ queryKey: categoriesKey(storeId), exact: true }),
      invalidateUserData(queryClient, storeId),
    ]);
  }

  const publish = useMutation({
    mutationFn: ({ storeId, draft }: { storeId: number; draft: DraftItem[] }) => api<IncomeConfigResponse>(`/admin/stores/${storeId}/income-config`, {
      method: "PUT",
      body: JSON.stringify({
        enabled: draft.length > 0,
        items: draft.map(({ category_id, name, include_in_total, is_active }, sort_order) => ({
          category_id,
          name: name.trim(),
          include_in_total,
          is_active,
          sort_order,
        })),
      }),
    }),
    onSuccess: async (config) => {
      queryClient.setQueryData(configKey(config.store_id), config);
      if (config.store_id === selectedStoreId) {
        setItems(configItems(config));
        setDraftStoreId(config.store_id);
      }
      await refreshStore(config.store_id);
    },
  });
  const archive = useMutation({
    mutationFn: (categoryId: number) => api<CategoryWithArchive>(`/admin/income-categories/${categoryId}/archive`, { method: "POST" }),
    onSuccess: async (category) => {
      if (category.store_id === selectedStoreId) {
        setItems((current) => current.filter((item) => item.category_id !== category.id).map((item, sort_order) => ({ ...item, sort_order })));
      }
      await refreshStore(category.store_id);
    },
  });
  const restore = useMutation({
    mutationFn: (categoryId: number) => api<CategoryWithArchive>(`/admin/income-categories/${categoryId}/restore`, { method: "POST" }),
    onSuccess: async (category) => {
      if (category.store_id === selectedStoreId) {
        setItems((current) => current.some((item) => item.category_id === category.id) ? current : [
          ...current,
          { key: `category-${category.id}`, category_id: category.id, name: category.name, include_in_total: category.include_in_total, is_active: true, sort_order: current.length },
        ]);
      }
      await queryClient.invalidateQueries({ queryKey: categoriesKey(category.store_id), exact: true });
    },
  });
  const deleteUnused = useMutation({
    mutationFn: ({ categoryId }: { categoryId: number; storeId: number }) => api<void>(`/admin/income-categories/${categoryId}`, { method: "DELETE" }),
    onSuccess: async (_, { storeId }) => { await refreshStore(storeId); },
  });

  function update(key: string, patch: Partial<DraftItem>) {
    setItems((current) => current.map((item) => item.key === key ? { ...item, ...patch } : item));
  }

  function move(index: number, offset: -1 | 1) {
    setItems((current) => {
      const target = index + offset;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next.map((item, sort_order) => ({ ...item, sort_order }));
    });
  }

  function addItem() {
    const name = newName.trim();
    if (!name) return;
    setItems((current) => [...current, {
      key: `new-${++nextDraftKey}`,
      category_id: null,
      name,
      include_in_total: true,
      is_active: true,
      sort_order: current.length,
    }]);
    setNewName("");
  }

  const included = items.filter((item) => item.is_active && item.include_in_total && item.name.trim()).map((item) => item.name.trim());
  const excluded = items.filter((item) => item.is_active && !item.include_in_total && item.name.trim()).map((item) => item.name.trim());
  const formula = `营业额 = ${included.length ? included.join(" + ") : "0"}${excluded.length ? `；“${excluded.join("、")}”只记录，不计入营业额` : ""}`;
  const archived = categories.data?.filter((category) => category.archived_at !== null) ?? [];
  const lifecyclePending = archive.isPending || restore.isPending || deleteUnused.isPending;

  return <div className="space-y-4">
    <div className="space-y-1">
      <label htmlFor="income-store">收入项目门店</label>
      <select id="income-store" className="h-9 w-full max-w-sm rounded-md border px-2" value={selectedStoreId ?? ""} onChange={(event) => onSelectedStoreChange(event.target.value ? Number(event.target.value) : null)}>
        <option value="">请选择门店</option>
        {stores.data?.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
      </select>
    </div>
    <ErrorMessage error={stores.error ?? currentConfig.error ?? categories.error ?? publish.error ?? archive.error ?? restore.error ?? deleteUnused.error} />
    {selectedStoreId !== null && <>
      <div className="rounded-lg border bg-muted/30 p-4">
        <p className="font-medium">营业额计算预览</p>
        <p className="text-sm text-muted-foreground">{formula}</p>
      </div>
      <div className="flex flex-col gap-2 rounded-lg border p-4 sm:flex-row">
        <Input aria-label="新收入项目名称" placeholder="例如：现金、刷卡" value={newName} onChange={(event) => setNewName(event.target.value)} />
        <Button type="button" variant="outline" onClick={addItem}>添加收入项目</Button>
      </div>
      {currentConfig.isLoading ? <p>正在加载收入项目…</p> : <ol className="space-y-3">
        {items.map((item, index) => <li className="grid gap-3 rounded-lg border p-3 md:grid-cols-[minmax(10rem,1fr)_auto_auto]" key={item.key}>
          <Input aria-label={`项目名称 ${item.name}`} value={item.name} onChange={(event) => update(item.key, { name: event.target.value })} />
          <label className="flex items-center gap-2"><input aria-label={`计入营业额 ${item.name}`} checked={item.include_in_total} type="checkbox" onChange={(event) => update(item.key, { include_in_total: event.target.checked })} />计入营业额</label>
          <div className="flex flex-wrap gap-2">
            <Button aria-label={`上移 ${item.name}`} disabled={index === 0} type="button" variant="outline" onClick={() => move(index, -1)}>上移</Button>
            <Button aria-label={`下移 ${item.name}`} disabled={index === items.length - 1} type="button" variant="outline" onClick={() => move(index, 1)}>下移</Button>
            {item.category_id !== null
              ? <Button aria-label={`归档 ${item.name}`} disabled={lifecyclePending} type="button" variant="outline" onClick={() => archive.mutate(item.category_id!)}>归档</Button>
              : <Button aria-label={`移除 ${item.name}`} type="button" variant="outline" onClick={() => setItems((current) => current.filter((candidate) => candidate.key !== item.key).map((candidate, sort_order) => ({ ...candidate, sort_order })))}>移除</Button>}
          </div>
        </li>)}
      </ol>}
      <Button disabled={publish.isPending || currentConfig.isLoading || draftStoreId !== selectedStoreId || items.some((item) => !item.name.trim())} type="button" onClick={() => {
        if (selectedStoreId !== null) publish.mutate({ storeId: selectedStoreId, draft: items });
      }}>{publish.isPending ? "保存中…" : "保存并发布"}</Button>
      {archived.length > 0 && <section className="space-y-2 rounded-lg border p-4" aria-label="已归档收入项目">
        <h2 className="font-medium">已归档项目</h2>
        <ul className="space-y-2">{archived.map((category) => <li className="flex flex-wrap items-center justify-between gap-2" key={category.id}>
          <span>{category.name}</span>
          <div className="flex gap-2">
            <Button aria-label={`恢复 ${category.name}`} disabled={lifecyclePending} type="button" variant="outline" onClick={() => restore.mutate(category.id)}>恢复</Button>
            <Button aria-label={`永久删除 ${category.name}`} disabled={lifecyclePending} type="button" variant="outline" onClick={() => {
              if (window.confirm(`永久删除后无法恢复，确定删除“${category.name}”吗？`)) {
                deleteUnused.mutate({ categoryId: category.id, storeId: category.store_id });
              }
            }}>永久删除</Button>
          </div>
        </li>)}</ul>
      </section>}
    </>}
  </div>;
}
