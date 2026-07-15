import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "@/api/client";
import type { AdminStore, AdminUser, IncomeCategory, ScheduledTaskLog, SystemAlert, UserRole } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { invalidateUserData } from "@/lib/user-api";
import { accessibleStoresKey } from "@/stores/StoreProvider";

export const adminKeys = {
  users: ["admin", "users"] as const,
  stores: ["admin", "stores"] as const,
  alerts: ["admin", "alerts"] as const,
  taskLogs: ["admin", "task-logs"] as const,
  members: (storeId: number) => ["admin", "stores", storeId, "members"] as const,
  categories: (storeId: number) => ["admin", "income-categories", storeId] as const,
  operations: (userId: number) => ["admin", "users", userId, "operations"] as const,
};

type UserOperation = { id: number; description: string; operation_type: string; created_at: string };

function ErrorMessage({ error }: { error: Error | null }) {
  if (!error) return null;
  return <p role="alert" className="text-sm text-destructive">{error instanceof ApiError ? error.detail : "请求失败"}</p>;
}

export function AdminPage() {
  const queryClient = useQueryClient();
  const [role, setRole] = useState<UserRole>("user");
  const [memberStoreId, setMemberStoreId] = useState<number | null>(null);
  const [memberIds, setMemberIds] = useState<number[]>([]);
  const [categoryStoreId, setCategoryStoreId] = useState<number | null>(null);
  const [historyUserId, setHistoryUserId] = useState<number | null>(null);
  const users = useQuery({ queryKey: adminKeys.users, queryFn: () => api<AdminUser[]>("/admin/users") });
  const stores = useQuery({ queryKey: adminKeys.stores, queryFn: () => api<AdminStore[]>("/admin/stores") });
  const alerts = useQuery({ queryKey: adminKeys.alerts, queryFn: () => api<SystemAlert[]>("/admin/alerts") });
  const taskLogs = useQuery({ queryKey: adminKeys.taskLogs, queryFn: () => api<ScheduledTaskLog[]>("/admin/task-logs") });
  const members = useQuery({
    queryKey: adminKeys.members(memberStoreId ?? 0),
    queryFn: () => api<AdminUser[]>(`/admin/stores/${memberStoreId}/members`),
    enabled: memberStoreId !== null,
  });
  const categories = useQuery({
    queryKey: adminKeys.categories(categoryStoreId ?? 0),
    queryFn: () => api<IncomeCategory[]>(`/admin/income-categories?store_id=${categoryStoreId}`),
    enabled: categoryStoreId !== null,
  });
  const operations = useQuery({
    queryKey: adminKeys.operations(historyUserId ?? 0),
    queryFn: () => api<UserOperation[]>(`/admin/users/${historyUserId}/operations`),
    enabled: historyUserId !== null,
  });
  const createUser = useMutation({
    mutationFn: (input: { username: string; password: string; role: UserRole }) =>
      api<AdminUser>("/admin/users", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminKeys.users, exact: true }),
  });
  const createStore = useMutation({
    mutationFn: (input: { name: string; address: string; latitude: number; longitude: number; timezone: string }) =>
      api<AdminStore>("/admin/stores", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: adminKeys.stores, exact: true });
      await queryClient.invalidateQueries({ queryKey: accessibleStoresKey, exact: true });
    },
  });
  const patchUser = useMutation({
    mutationFn: ({ userId, body }: { userId: number; body: { password?: string; is_active?: boolean } }) =>
      api<AdminUser>(`/admin/users/${userId}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminKeys.users, exact: true }),
  });
  const patchStore = useMutation({
    mutationFn: ({ storeId, body }: { storeId: number; body: Partial<Omit<AdminStore, "id">> }) =>
      api<AdminStore>(`/admin/stores/${storeId}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: adminKeys.stores, exact: true });
      await queryClient.invalidateQueries({ queryKey: accessibleStoresKey, exact: true });
    },
  });
  const replaceMembers = useMutation({
    mutationFn: (input: { storeId: number; userIds: number[] }) =>
      api<{ store_id: number; user_ids: number[] }>(`/admin/stores/${input.storeId}/members`, {
        method: "PUT", body: JSON.stringify({ user_ids: input.userIds }),
      }),
    onSuccess: async (_data, input) => {
      await queryClient.invalidateQueries({ queryKey: adminKeys.members(input.storeId), exact: true });
      await queryClient.invalidateQueries({ queryKey: accessibleStoresKey, exact: true });
    },
  });
  const createCategory = useMutation({
    mutationFn: (input: { store_id: number; name: string; include_in_total: boolean; sort_order: number }) =>
      api<IncomeCategory>("/admin/income-categories", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: async (category) => {
      await queryClient.invalidateQueries({ queryKey: adminKeys.categories(category.store_id), exact: true });
      await invalidateUserData(queryClient, category.store_id);
    },
  });
  const patchCategory = useMutation({
    mutationFn: ({ categoryId, body }: { categoryId: number; storeId: number; body: Partial<IncomeCategory> }) =>
      api<IncomeCategory>(`/admin/income-categories/${categoryId}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: async (category) => {
      await queryClient.invalidateQueries({ queryKey: adminKeys.categories(category.store_id), exact: true });
      await invalidateUserData(queryClient, category.store_id);
    },
  });

  useEffect(() => {
    if (members.data) setMemberIds(members.data.map((user) => user.id));
  }, [members.data]);
  const canSaveMembers = memberStoreId !== null && users.isSuccess && members.isSuccess;

  function submitUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    createUser.mutate({ username: String(data.get("username")), password: String(data.get("password")), role }, { onSuccess: () => form.reset() });
  }

  function submitStore(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    createStore.mutate({
      name: String(data.get("name")), address: String(data.get("address")),
      latitude: Number(data.get("latitude")), longitude: Number(data.get("longitude")),
      timezone: String(data.get("timezone")),
    }, { onSuccess: () => form.reset() });
  }

  return (
    <section className="space-y-4">
      <div><h1 className="text-2xl font-semibold">系统管理</h1><p className="text-sm text-muted-foreground">配置用户、门店与业务基础数据。</p></div>
      <Tabs defaultValue="users">
        <TabsList className="h-auto w-full flex-wrap justify-start">
          <TabsTrigger value="users">用户</TabsTrigger><TabsTrigger value="stores">门店</TabsTrigger><TabsTrigger value="members">成员</TabsTrigger><TabsTrigger value="categories">收入分类</TabsTrigger><TabsTrigger value="alerts">告警</TabsTrigger><TabsTrigger value="tasks">任务日志</TabsTrigger>
        </TabsList>
        <TabsContent value="users" className="space-y-4">
          <ErrorMessage error={users.error} /><ErrorMessage error={createUser.error} /><ErrorMessage error={patchUser.error} />
          <form className="grid gap-3 rounded-lg border p-4 md:grid-cols-4" onSubmit={submitUser}>
            <div><label htmlFor="new-username">新用户名</label><Input id="new-username" name="username" minLength={3} required /></div>
            <div><label htmlFor="new-password">初始密码</label><Input id="new-password" name="password" minLength={8} required type="password" /></div>
            <div><label htmlFor="new-role">角色</label><select id="new-role" className="h-9 w-full rounded-md border px-2" value={role} onChange={(event) => setRole(event.target.value as UserRole)}><option value="user">普通用户</option><option value="admin">管理员</option></select></div>
            <Button className="self-end" disabled={createUser.isPending} type="submit">{createUser.isPending ? "添加中…" : "添加用户"}</Button>
          </form>
          <ul className="divide-y rounded-lg border">{users.data?.map((user) => <li className="grid gap-2 p-3 md:grid-cols-[1fr_auto]" key={user.id}>
            <div><span>{user.username}</span><span className="ml-2 text-sm text-muted-foreground">{user.role} · {user.is_active ? "启用" : "停用"}</span></div>
            <div className="flex flex-wrap gap-2">
              <Button aria-label={`${user.is_active ? "停用" : "启用"}用户 ${user.username}`} disabled={patchUser.isPending} size="sm" variant="outline" onClick={() => patchUser.mutate({ userId: user.id, body: { is_active: !user.is_active } })}>{user.is_active ? "停用" : "启用"}</Button>
              <Button aria-label={`操作历史 ${user.username}`} size="sm" variant="outline" onClick={() => setHistoryUserId(user.id)}>操作历史</Button>
            </div>
            <form className="flex gap-2 md:col-span-2" onSubmit={(event) => { event.preventDefault(); const form = event.currentTarget; const password = String(new FormData(form).get("password")); patchUser.mutate({ userId: user.id, body: { password } }, { onSuccess: () => form.reset() }); }}>
              <label className="sr-only" htmlFor={`password-${user.id}`}>新密码 {user.username}</label><Input disabled={patchUser.isPending} id={`password-${user.id}`} minLength={8} name="password" placeholder="新密码" required type="password" />
              <Button aria-label={`修改密码 ${user.username}`} disabled={patchUser.isPending} size="sm" type="submit">修改密码</Button>
            </form>
          </li>)}</ul>
          {historyUserId !== null && <section className="rounded-lg border p-3"><div className="flex justify-between"><h2 className="font-medium">用户操作历史</h2><Button size="sm" variant="ghost" onClick={() => setHistoryUserId(null)}>关闭</Button></div><ErrorMessage error={operations.error} /><ul>{operations.data?.map((entry) => <li className="border-t py-2" key={entry.id}>{entry.description}</li>)}</ul></section>}
        </TabsContent>
        <TabsContent value="stores" className="space-y-4">
          <ErrorMessage error={stores.error} /><ErrorMessage error={createStore.error} /><ErrorMessage error={patchStore.error} />
          <form className="grid gap-3 rounded-lg border p-4 md:grid-cols-3" onSubmit={submitStore}>
            <div><label htmlFor="store-name">门店名称</label><Input id="store-name" name="name" required /></div>
            <div><label htmlFor="store-address">地址</label><Input id="store-address" name="address" required /></div>
            <div><label htmlFor="store-latitude">纬度</label><Input id="store-latitude" name="latitude" required type="number" step="any" /></div>
            <div><label htmlFor="store-longitude">经度</label><Input id="store-longitude" name="longitude" required type="number" step="any" /></div>
            <div><label htmlFor="store-timezone">时区</label><Input defaultValue="Europe/Rome" id="store-timezone" name="timezone" required /></div>
            <Button className="self-end" disabled={createStore.isPending} type="submit">{createStore.isPending ? "添加中…" : "添加门店"}</Button>
          </form>
          <ul className="space-y-3">{stores.data?.map((store) => <li className="rounded-lg border p-3" key={store.id}><form className="grid gap-2 md:grid-cols-3" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); patchStore.mutate({ storeId: store.id, body: { name: String(data.get("name")), address: String(data.get("address")), latitude: String(data.get("latitude")), longitude: String(data.get("longitude")), timezone: String(data.get("timezone")) } }); }}>
            <div><label htmlFor={`store-name-${store.id}`}>门店名称 {store.name}</label><Input defaultValue={store.name} id={`store-name-${store.id}`} name="name" required /></div>
            <div><label htmlFor={`store-address-${store.id}`}>地址 {store.name}</label><Input defaultValue={store.address} id={`store-address-${store.id}`} name="address" required /></div>
            <div><label htmlFor={`store-lat-${store.id}`}>纬度 {store.name}</label><Input defaultValue={store.latitude} id={`store-lat-${store.id}`} name="latitude" required type="number" step="any" /></div>
            <div><label htmlFor={`store-lon-${store.id}`}>经度 {store.name}</label><Input defaultValue={store.longitude} id={`store-lon-${store.id}`} name="longitude" required type="number" step="any" /></div>
            <div><label htmlFor={`store-tz-${store.id}`}>时区 {store.name}</label><Input defaultValue={store.timezone} id={`store-tz-${store.id}`} name="timezone" required /></div>
            <div className="flex items-end gap-2"><Button aria-label={`保存门店 ${store.name}`} disabled={patchStore.isPending} type="submit">保存</Button><Button aria-label={`${store.is_active ? "停用" : "启用"}门店 ${store.name}`} disabled={patchStore.isPending} type="button" variant="outline" onClick={() => patchStore.mutate({ storeId: store.id, body: { is_active: !store.is_active } })}>{store.is_active ? "停用" : "启用"}</Button></div>
          </form></li>)}</ul>
        </TabsContent>
        <TabsContent value="members" className="space-y-4">
          <label htmlFor="member-store">成员门店</label>
          <select id="member-store" className="h-9 w-full max-w-sm rounded-md border px-2" value={memberStoreId ?? ""} onChange={(event) => { setMemberStoreId(event.target.value ? Number(event.target.value) : null); setMemberIds([]); }}>
            <option value="">请选择门店</option>{stores.data?.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
          </select>
          <ErrorMessage error={users.error} /><ErrorMessage error={members.error} /><ErrorMessage error={replaceMembers.error} />
          {memberStoreId !== null && <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); if (canSaveMembers) replaceMembers.mutate({ storeId: memberStoreId, userIds: memberIds }); }}>
            <fieldset className="space-y-2"><legend>门店成员</legend>{users.data?.map((user) => <label className="flex items-center gap-2" key={user.id}><input checked={memberIds.includes(user.id)} onChange={(event) => setMemberIds((current) => event.target.checked ? [...current, user.id].sort((a, b) => a - b) : current.filter((id) => id !== user.id))} type="checkbox" />{user.username}</label>)}</fieldset>
            <Button disabled={!canSaveMembers || replaceMembers.isPending} type="submit">{replaceMembers.isPending ? "保存中…" : "保存成员"}</Button>
          </form>}
        </TabsContent>
        <TabsContent value="categories" className="space-y-4">
          <label htmlFor="category-store">分类门店</label>
          <select id="category-store" className="h-9 w-full max-w-sm rounded-md border px-2" value={categoryStoreId ?? ""} onChange={(event) => setCategoryStoreId(event.target.value ? Number(event.target.value) : null)}>
            <option value="">请选择门店</option>{stores.data?.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
          </select>
          <ErrorMessage error={categories.error} /><ErrorMessage error={createCategory.error} /><ErrorMessage error={patchCategory.error} />
          {categoryStoreId !== null && <>
            <form className="grid gap-3 rounded-lg border p-4 md:grid-cols-4" onSubmit={(event) => {
              event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
              createCategory.mutate({ store_id: categoryStoreId, name: String(data.get("name")), include_in_total: data.get("include") === "on", sort_order: Number(data.get("sort_order")) }, { onSuccess: () => form.reset() });
            }}>
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
        </TabsContent>
        <TabsContent value="alerts"><ErrorMessage error={alerts.error} /><ul>{alerts.data?.map((item) => <li key={item.id}>{item.level}: {item.message}</li>)}</ul></TabsContent>
        <TabsContent value="tasks"><ErrorMessage error={taskLogs.error} /><ul>{taskLogs.data?.map((item) => <li key={item.id}>{item.task_type}: {item.status}</li>)}</ul></TabsContent>
      </Tabs>
    </section>
  );
}
