import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";

import { api, ApiError } from "@/api/client";
import type { AdminStore, IncomeCategory } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { invalidateUserData } from "@/lib/user-api";

const storesKey = ["admin", "stores"] as const;
const categoriesKey = (storeId: number) => ["admin", "income-categories", storeId] as const;

function ErrorMessage({ error }: { error: Error | null }) {
  if (!error) return null;
  return <p role="alert" className="text-sm text-destructive">{error instanceof ApiError ? error.detail : "请求失败"}</p>;
}

export function IncomeItemsPanel({ selectedStoreId, onSelectedStoreChange }: { selectedStoreId: number | null; onSelectedStoreChange: (storeId: number | null) => void }) {
  const queryClient = useQueryClient();
  const stores = useQuery({ queryKey: storesKey, queryFn: () => api<AdminStore[]>("/admin/stores") });
  const categories = useQuery({ queryKey: categoriesKey(selectedStoreId ?? 0), queryFn: () => api<IncomeCategory[]>(`/admin/income-categories?store_id=${selectedStoreId}`), enabled: selectedStoreId !== null });
  const createCategory = useMutation({
    mutationFn: (input: { store_id: number; name: string; include_in_total: boolean; sort_order: number }) => api<IncomeCategory>("/admin/income-categories", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: async (category) => { await queryClient.invalidateQueries({ queryKey: categoriesKey(category.store_id), exact: true }); await invalidateUserData(queryClient, category.store_id); },
  });
  const patchCategory = useMutation({
    mutationFn: ({ categoryId, body }: { categoryId: number; storeId: number; body: Partial<IncomeCategory> }) => api<IncomeCategory>(`/admin/income-categories/${categoryId}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: async (category) => { await queryClient.invalidateQueries({ queryKey: categoriesKey(category.store_id), exact: true }); await invalidateUserData(queryClient, category.store_id); },
  });

  return <>
    <label htmlFor="category-store">分类门店</label>
    <select id="category-store" className="h-9 w-full max-w-sm rounded-md border px-2" value={selectedStoreId ?? ""} onChange={(event) => onSelectedStoreChange(event.target.value ? Number(event.target.value) : null)}>
      <option value="">请选择门店</option>{stores.data?.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
    </select>
    <ErrorMessage error={stores.error} /><ErrorMessage error={categories.error} /><ErrorMessage error={createCategory.error} /><ErrorMessage error={patchCategory.error} />
    {selectedStoreId !== null && <>
      <form className="grid gap-3 rounded-lg border p-4 md:grid-cols-4" onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); createCategory.mutate({ store_id: selectedStoreId, name: String(data.get("name")), include_in_total: data.get("include") === "on", sort_order: Number(data.get("sort_order")) }, { onSuccess: () => form.reset() }); }}>
        <div><label htmlFor="category-name">分类名称</label><Input id="category-name" name="name" required /></div>
        <div><label htmlFor="category-sort">排序</label><Input defaultValue="0" id="category-sort" name="sort_order" required type="number" /></div>
        <label className="flex items-center gap-2 self-end pb-2"><input defaultChecked name="include" type="checkbox" />计入总收入</label>
        <Button className="self-end" disabled={createCategory.isPending} type="submit">{createCategory.isPending ? "添加中…" : "添加分类"}</Button>
      </form>
      <ul className="space-y-3">{categories.data?.map((category) => <li className="rounded-lg border p-3" key={category.id}><form className="grid gap-2 md:grid-cols-4" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); patchCategory.mutate({ categoryId: category.id, storeId: category.store_id, body: { name: String(data.get("name")), sort_order: Number(data.get("sort_order")), include_in_total: data.get("include_in_total") === "on" } }); }}>
        <div><label htmlFor={`category-name-${category.id}`}>分类名称 {category.name}</label><Input defaultValue={category.name} id={`category-name-${category.id}`} name="name" required /></div>
        <div><label htmlFor={`category-sort-${category.id}`}>排序 {category.name}</label><Input defaultValue={category.sort_order} id={`category-sort-${category.id}`} name="sort_order" type="number" /></div>
        <label className="flex items-center gap-2"><input aria-label={`计入总收入 ${category.name}`} defaultChecked={category.include_in_total} name="include_in_total" type="checkbox" />计入总收入</label>
        <div className="flex items-end gap-2"><Button aria-label={`保存分类 ${category.name}`} disabled={patchCategory.isPending} type="submit">保存</Button><Button aria-label={`${category.is_active ? "停用" : "启用"}分类 ${category.name}`} disabled={patchCategory.isPending} type="button" variant="outline" onClick={() => patchCategory.mutate({ categoryId: category.id, storeId: category.store_id, body: { is_active: !category.is_active } })}>{category.is_active ? "停用" : "启用"}</Button></div>
      </form></li>)}</ul>
    </>}
  </>;
}
