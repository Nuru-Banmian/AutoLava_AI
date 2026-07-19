import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, friendlyApiError } from "@/api/client";
import type { IncomeCategory, IncomeConfigResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { invalidateUserData } from "@/lib/user-api";

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
      key: `category-${item.id}`,
      category_id: item.id,
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

export interface IncomeItemsPanelProps {
  storeId: number;
  onDirtyChange(dirty: boolean): void;
}

interface OperationState {
  requestId: number;
  storeId: number;
  pending: boolean;
  error: unknown;
}

export function IncomeItemsPanel({ storeId, onDirtyChange }: IncomeItemsPanelProps) {
  const queryClient = useQueryClient();
  const mountedRef = useRef(false);
  const storeIdRef = useRef(storeId);
  const requestSequence = useRef(0);
  const [items, setItems] = useState<DraftItem[]>([]);
  const [draftStoreId, setDraftStoreId] = useState<number | null>(null);
  const [draftEnabled, setDraftEnabled] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [newName, setNewName] = useState("");
  const [operation, setOperation] = useState<OperationState | null>(null);
  storeIdRef.current = storeId;
  const currentConfig = useQuery({
    queryKey: configKey(storeId),
    queryFn: () => api<IncomeConfigResponse>(`/income-config/${storeId}/current`),
  });
  const categories = useQuery({
    queryKey: categoriesKey(storeId),
    queryFn: () => api<CategoryWithArchive[]>(`/admin/income-categories?store_id=${storeId}`),
  });

  useEffect(() => {
    setItems([]);
    setDraftStoreId(null);
    setDraftEnabled(false);
    setIsDirty(false);
    setNewName("");
    setOperation(null);
  }, [storeId]);

  useEffect(() => {
    if (currentConfig.data && currentConfig.data.store_id === storeId && !isDirty) {
      setItems(configItems(currentConfig.data));
      setDraftStoreId(currentConfig.data.store_id);
      setDraftEnabled(currentConfig.data.enabled);
    }
  }, [currentConfig.data, isDirty, storeId]);

  useEffect(() => {
    onDirtyChange(isDirty);
  }, [isDirty, onDirtyChange]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestSequence.current += 1;
      onDirtyChange(false);
    };
  }, [onDirtyChange]);

  async function refreshStore(storeId: number) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: configKey(storeId), exact: true }),
      queryClient.invalidateQueries({ queryKey: categoriesKey(storeId), exact: true }),
      invalidateUserData(queryClient, storeId),
    ]);
  }

  function beginOperation(capturedStoreId: number) {
    const requestId = ++requestSequence.current;
    setOperation({ requestId, storeId: capturedStoreId, pending: true, error: null });
    return requestId;
  }

  function isCurrentRequest(requestId: number, capturedStoreId: number) {
    return mountedRef.current
      && requestSequence.current === requestId
      && storeIdRef.current === capturedStoreId;
  }

  function finishOperation(requestId: number, capturedStoreId: number, error: unknown = null) {
    if (!isCurrentRequest(requestId, capturedStoreId)) return;
    setOperation({ requestId, storeId: capturedStoreId, pending: false, error });
  }

  async function publishDraft() {
    const capturedStoreId = storeId;
    const capturedDraft = items;
    const capturedEnabled = draftEnabled;
    const requestId = beginOperation(capturedStoreId);
    try {
      const config = await api<IncomeConfigResponse>(`/admin/stores/${capturedStoreId}/income-config`, {
      method: "PUT",
      body: JSON.stringify({
        enabled: capturedEnabled,
        items: capturedDraft.map(({ category_id, name, include_in_total, is_active }, sort_order) => ({
          category_id,
          name: name.trim(),
          include_in_total,
          is_active,
          sort_order,
        })),
      }),
      });
      queryClient.setQueryData(configKey(config.store_id), config);
      await refreshStore(capturedStoreId);
      if (isCurrentRequest(requestId, capturedStoreId)) {
        setItems(configItems(config));
        setDraftStoreId(config.store_id);
        setDraftEnabled(config.enabled);
        setIsDirty(false);
      }
      finishOperation(requestId, capturedStoreId);
    } catch (error) {
      finishOperation(requestId, capturedStoreId, error);
    }
  }

  async function archiveCategory(categoryId: number) {
    const capturedStoreId = storeId;
    const requestId = beginOperation(capturedStoreId);
    try {
      const category = await api<CategoryWithArchive>(`/admin/income-categories/${categoryId}/archive`, { method: "POST" });
      if (isCurrentRequest(requestId, capturedStoreId)) {
        setItems((current) => current.filter((item) => item.category_id !== category.id).map((item, sort_order) => ({ ...item, sort_order })));
      }
      await refreshStore(capturedStoreId);
      finishOperation(requestId, capturedStoreId);
    } catch (error) {
      finishOperation(requestId, capturedStoreId, error);
    }
  }

  async function restoreCategory(categoryId: number, capturedStoreId: number) {
    const requestId = beginOperation(capturedStoreId);
    try {
      const category = await api<CategoryWithArchive>(`/admin/income-categories/${categoryId}/restore`, { method: "POST" });
      if (isCurrentRequest(requestId, capturedStoreId)) {
        setItems((current) => current.some((item) => item.category_id === category.id) ? current : [
          ...current,
          { key: `category-${category.id}`, category_id: category.id, name: category.name, include_in_total: category.include_in_total, is_active: true, sort_order: current.length },
        ]);
        setIsDirty(true);
      }
      await queryClient.invalidateQueries({ queryKey: categoriesKey(capturedStoreId), exact: true });
      finishOperation(requestId, capturedStoreId);
    } catch (error) {
      finishOperation(requestId, capturedStoreId, error);
    }
  }

  async function deleteCategory(categoryId: number, capturedStoreId: number) {
    const requestId = beginOperation(capturedStoreId);
    try {
      await api<void>(`/admin/income-categories/${categoryId}`, { method: "DELETE" });
      await refreshStore(capturedStoreId);
      finishOperation(requestId, capturedStoreId);
    } catch (error) {
      finishOperation(requestId, capturedStoreId, error);
    }
  }

  function update(key: string, patch: Partial<DraftItem>) {
    setItems((current) => current.map((item) => item.key === key ? { ...item, ...patch } : item));
    setIsDirty(true);
  }

  function move(index: number, offset: -1 | 1) {
    setItems((current) => {
      const target = index + offset;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next.map((item, sort_order) => ({ ...item, sort_order }));
    });
    setIsDirty(true);
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
    setIsDirty(true);
    setNewName("");
  }

  const included = items.filter((item) => item.is_active && item.include_in_total && item.name.trim()).map((item) => item.name.trim());
  const excluded = items.filter((item) => item.is_active && !item.include_in_total && item.name.trim()).map((item) => item.name.trim());
  const formula = `营业额 = ${included.length ? included.join(" + ") : "0"}${excluded.length ? `；“${excluded.join("、")}”只记录，不计入营业额` : ""}`;
  const archived = categories.data?.filter((category) => category.archived_at !== null) ?? [];
  const operationPending = Boolean(operation?.storeId === storeId && operation?.pending);
  const mutationError = operation?.storeId === storeId ? operation.error : null;

  return <section className="space-y-4 rounded-lg border bg-card p-4" aria-labelledby="income-items-title">
    <h2 id="income-items-title" className="font-medium">收入项目</h2>
    <ErrorMessage error={currentConfig.error ?? categories.error ?? mutationError} />
    <>
      <label className="flex items-center gap-2">
        <input aria-label="启用收入项目明细" checked={draftEnabled} disabled={operationPending || currentConfig.isLoading || draftStoreId !== storeId} type="checkbox" onChange={(event) => {
          setDraftEnabled(event.target.checked);
          setIsDirty(true);
        }} />
        启用收入项目明细
      </label>
      <div className="rounded-lg border bg-muted/30 p-4">
        <p className="font-medium">营业额计算预览</p>
        <p className="text-sm text-muted-foreground">{formula}</p>
      </div>
      <div className="flex flex-col gap-2 rounded-lg border p-4 sm:flex-row">
        <Input aria-label="新收入项目名称" disabled={operationPending} placeholder="例如：现金、刷卡" value={newName} onChange={(event) => setNewName(event.target.value)} />
        <Button disabled={operationPending} type="button" variant="outline" onClick={addItem}>添加收入项目</Button>
      </div>
      {currentConfig.isLoading ? <p>正在加载收入项目…</p> : <ol className="space-y-3">
        {items.map((item, index) => <li className="grid gap-3 rounded-lg border p-3 md:grid-cols-[minmax(10rem,1fr)_auto_auto]" key={item.key}>
          <Input aria-label={`项目名称 ${item.name}`} disabled={operationPending} value={item.name} onChange={(event) => update(item.key, { name: event.target.value })} />
          <label className="flex items-center gap-2"><input aria-label={`计入营业额 ${item.name}`} checked={item.include_in_total} disabled={operationPending} type="checkbox" onChange={(event) => update(item.key, { include_in_total: event.target.checked })} />计入营业额</label>
          <div className="flex flex-wrap gap-2">
            <Button aria-label={`上移 ${item.name}`} disabled={operationPending || index === 0} type="button" variant="outline" onClick={() => move(index, -1)}>上移</Button>
            <Button aria-label={`下移 ${item.name}`} disabled={operationPending || index === items.length - 1} type="button" variant="outline" onClick={() => move(index, 1)}>下移</Button>
            {item.category_id !== null
              ? <Button aria-label={`归档 ${item.name}`} disabled={operationPending} type="button" variant="outline" onClick={() => void archiveCategory(item.category_id!)}>归档</Button>
              : <Button aria-label={`移除 ${item.name}`} disabled={operationPending} type="button" variant="outline" onClick={() => {
                setItems((current) => current.filter((candidate) => candidate.key !== item.key).map((candidate, sort_order) => ({ ...candidate, sort_order })));
                setIsDirty(true);
              }}>移除</Button>}
          </div>
        </li>)}
      </ol>}
      <Button aria-busy={operationPending || undefined} disabled={operationPending || currentConfig.isLoading || draftStoreId !== storeId || items.some((item) => !item.name.trim())} type="button" onClick={() => void publishDraft()}>保存</Button>
      {archived.length > 0 && <section className="space-y-2 rounded-lg border p-4" aria-label="已归档收入项目">
        <h2 className="font-medium">已归档项目</h2>
        <ul className="space-y-2">{archived.map((category) => <li className="flex flex-wrap items-center justify-between gap-2" key={category.id}>
          <span>{category.name}</span>
          <div className="flex gap-2">
            <Button aria-label={`恢复 ${category.name}`} disabled={operationPending} type="button" variant="outline" onClick={() => void restoreCategory(category.id, category.store_id)}>恢复</Button>
            <Button aria-label={`永久删除 ${category.name}`} disabled={operationPending} type="button" variant="outline" onClick={() => {
              if (window.confirm(`永久删除后无法恢复，确定删除“${category.name}”吗？`)) {
                void deleteCategory(category.id, category.store_id);
              }
            }}>永久删除</Button>
          </div>
        </li>)}</ul>
      </section>}
    </>
  </section>;
}
