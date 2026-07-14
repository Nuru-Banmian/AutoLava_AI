import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "@/api/client";
import type { AdminStore, AdminUser, IncomeCategory, ScheduledTaskLog, SystemAlert, UserRole } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export const adminKeys = {
  users: ["admin", "users"] as const,
  stores: ["admin", "stores"] as const,
  alerts: ["admin", "alerts"] as const,
  taskLogs: ["admin", "task-logs"] as const,
  members: (storeId: number) => ["admin", "stores", storeId, "members"] as const,
  categories: (storeId: number) => ["admin", "income-categories", storeId] as const,
};

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
  const createUser = useMutation({
    mutationFn: (input: { username: string; password: string; role: UserRole }) =>
      api<AdminUser>("/admin/users", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminKeys.users, exact: true }),
  });
  const createStore = useMutation({
    mutationFn: (input: { name: string; address: string; latitude: number; longitude: number; timezone: string }) =>
      api<AdminStore>("/admin/stores", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminKeys.stores, exact: true }),
  });
  const replaceMembers = useMutation({
    mutationFn: (input: { storeId: number; userIds: number[] }) =>
      api<{ store_id: number; user_ids: number[] }>(`/admin/stores/${input.storeId}/members`, {
        method: "PUT", body: JSON.stringify({ user_ids: input.userIds }),
      }),
    onSuccess: (_data, input) => queryClient.invalidateQueries({ queryKey: adminKeys.members(input.storeId), exact: true }),
  });
  const createCategory = useMutation({
    mutationFn: (input: { store_id: number; name: string; include_in_total: boolean; sort_order: number }) =>
      api<IncomeCategory>("/admin/income-categories", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: (category) => queryClient.invalidateQueries({ queryKey: adminKeys.categories(category.store_id), exact: true }),
  });

  useEffect(() => {
    if (members.data) setMemberIds(members.data.map((user) => user.id));
  }, [members.data]);

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
          <ErrorMessage error={users.error} /><ErrorMessage error={createUser.error} />
          <form className="grid gap-3 rounded-lg border p-4 md:grid-cols-4" onSubmit={submitUser}>
            <div><label htmlFor="new-username">新用户名</label><Input id="new-username" name="username" minLength={3} required /></div>
            <div><label htmlFor="new-password">初始密码</label><Input id="new-password" name="password" minLength={8} required type="password" /></div>
            <div><label htmlFor="new-role">角色</label><select id="new-role" className="h-9 w-full rounded-md border px-2" value={role} onChange={(event) => setRole(event.target.value as UserRole)}><option value="user">普通用户</option><option value="admin">管理员</option></select></div>
            <Button className="self-end" disabled={createUser.isPending} type="submit">{createUser.isPending ? "添加中…" : "添加用户"}</Button>
          </form>
          <ul className="divide-y rounded-lg border">{users.data?.map((user) => <li className="flex justify-between p-3" key={user.id}><span>{user.username}</span><span>{user.role} · {user.is_active ? "启用" : "停用"}</span></li>)}</ul>
        </TabsContent>
        <TabsContent value="stores" className="space-y-4">
          <ErrorMessage error={stores.error} /><ErrorMessage error={createStore.error} />
          <form className="grid gap-3 rounded-lg border p-4 md:grid-cols-3" onSubmit={submitStore}>
            <div><label htmlFor="store-name">门店名称</label><Input id="store-name" name="name" required /></div>
            <div><label htmlFor="store-address">地址</label><Input id="store-address" name="address" required /></div>
            <div><label htmlFor="store-latitude">纬度</label><Input id="store-latitude" name="latitude" required type="number" step="any" /></div>
            <div><label htmlFor="store-longitude">经度</label><Input id="store-longitude" name="longitude" required type="number" step="any" /></div>
            <div><label htmlFor="store-timezone">时区</label><Input defaultValue="Europe/Rome" id="store-timezone" name="timezone" required /></div>
            <Button className="self-end" disabled={createStore.isPending} type="submit">{createStore.isPending ? "添加中…" : "添加门店"}</Button>
          </form>
          <ul>{stores.data?.map((store) => <li key={store.id}>{store.name} · {store.address}</li>)}</ul>
        </TabsContent>
        <TabsContent value="members" className="space-y-4">
          <label htmlFor="member-store">成员门店</label>
          <select id="member-store" className="h-9 w-full max-w-sm rounded-md border px-2" value={memberStoreId ?? ""} onChange={(event) => { setMemberStoreId(event.target.value ? Number(event.target.value) : null); setMemberIds([]); }}>
            <option value="">请选择门店</option>{stores.data?.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
          </select>
          <ErrorMessage error={members.error} /><ErrorMessage error={replaceMembers.error} />
          {memberStoreId !== null && <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); replaceMembers.mutate({ storeId: memberStoreId, userIds: memberIds }); }}>
            <fieldset className="space-y-2"><legend>门店成员</legend>{users.data?.map((user) => <label className="flex items-center gap-2" key={user.id}><input checked={memberIds.includes(user.id)} onChange={(event) => setMemberIds((current) => event.target.checked ? [...current, user.id].sort((a, b) => a - b) : current.filter((id) => id !== user.id))} type="checkbox" />{user.username}</label>)}</fieldset>
            <Button disabled={members.isLoading || replaceMembers.isPending} type="submit">{replaceMembers.isPending ? "保存中…" : "保存成员"}</Button>
          </form>}
        </TabsContent>
        <TabsContent value="categories" className="space-y-4">
          <label htmlFor="category-store">分类门店</label>
          <select id="category-store" className="h-9 w-full max-w-sm rounded-md border px-2" value={categoryStoreId ?? ""} onChange={(event) => setCategoryStoreId(event.target.value ? Number(event.target.value) : null)}>
            <option value="">请选择门店</option>{stores.data?.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
          </select>
          <ErrorMessage error={categories.error} /><ErrorMessage error={createCategory.error} />
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
            <ul>{categories.data?.map((category) => <li key={category.id}>{category.name} · {category.include_in_total ? "计入" : "不计入"}</li>)}</ul>
          </>}
        </TabsContent>
        <TabsContent value="alerts"><ErrorMessage error={alerts.error} /><ul>{alerts.data?.map((item) => <li key={item.id}>{item.level}: {item.message}</li>)}</ul></TabsContent>
        <TabsContent value="tasks"><ErrorMessage error={taskLogs.error} /><ul>{taskLogs.data?.map((item) => <li key={item.id}>{item.task_type}: {item.status}</li>)}</ul></TabsContent>
      </Tabs>
    </section>
  );
}
