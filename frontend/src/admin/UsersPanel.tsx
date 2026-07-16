import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "@/api/client";
import type { AdminStore, AdminUser, UserRole } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { accessibleStoresKey } from "@/stores/StoreProvider";

const usersKey = ["admin", "users"] as const;
const storesKey = ["admin", "stores"] as const;
const membersKey = (storeId: number) => ["admin", "stores", storeId, "members"] as const;
const operationsKey = (userId: number) => ["admin", "users", userId, "operations"] as const;
type UserOperation = { id: number; description: string; operation_type: string; created_at: string };
type UserPatchBody = { password?: string; role?: UserRole; is_active?: boolean; store_ids?: number[] };

function ErrorMessage({ error }: { error: Error | null }) {
  if (!error) return null;
  return <p role="alert" className="text-sm text-destructive">{error instanceof ApiError ? error.detail : "请求失败"}</p>;
}

export function UsersPanel({ selectedStoreId, onSelectedStoreChange }: { selectedStoreId: number | null; onSelectedStoreChange: (storeId: number | null) => void }) {
  const queryClient = useQueryClient();
  const [role, setRole] = useState<UserRole>("user");
  const [memberIds, setMemberIds] = useState<number[]>([]);
  const [historyUserId, setHistoryUserId] = useState<number | null>(null);
  const users = useQuery({ queryKey: usersKey, queryFn: () => api<AdminUser[]>("/admin/users") });
  const stores = useQuery({ queryKey: storesKey, queryFn: () => api<AdminStore[]>("/admin/stores") });
  const members = useQuery({ queryKey: membersKey(selectedStoreId ?? 0), queryFn: () => api<AdminUser[]>(`/admin/stores/${selectedStoreId}/members`), enabled: selectedStoreId !== null });
  const operations = useQuery({ queryKey: operationsKey(historyUserId ?? 0), queryFn: () => api<UserOperation[]>(`/admin/users/${historyUserId}/operations`), enabled: historyUserId !== null });
  const createUser = useMutation({ mutationFn: (input: { username: string; password: string; role: UserRole }) => api<AdminUser>("/admin/users", { method: "POST", body: JSON.stringify(input) }), onSuccess: () => queryClient.invalidateQueries({ queryKey: usersKey, exact: true }) });
  const patchUser = useMutation({ mutationFn: ({ userId, body }: { userId: number; body: UserPatchBody }) => api<AdminUser>(`/admin/users/${userId}`, { method: "PATCH", body: JSON.stringify(body) }), onSuccess: () => queryClient.invalidateQueries({ queryKey: usersKey, exact: true }) });
  const replaceMembers = useMutation({
    mutationFn: (input: { storeId: number; userIds: number[] }) => api<{ store_id: number; user_ids: number[] }>(`/admin/stores/${input.storeId}/members`, { method: "PUT", body: JSON.stringify({ user_ids: input.userIds }) }),
    onSuccess: async (_data, input) => { await queryClient.invalidateQueries({ queryKey: membersKey(input.storeId), exact: true }); await queryClient.invalidateQueries({ queryKey: accessibleStoresKey }); },
  });
  useEffect(() => { if (members.data) setMemberIds(members.data.map((user) => user.id)); }, [members.data]);
  const canSaveMembers = selectedStoreId !== null && users.isSuccess && members.isSuccess;

  function submitUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    createUser.mutate({ username: String(data.get("username")), password: String(data.get("password")), role }, { onSuccess: () => form.reset() });
  }

  return <>
    <ErrorMessage error={users.error} /><ErrorMessage error={createUser.error} /><ErrorMessage error={patchUser.error} />
    <p className="rounded-lg bg-blue-50 p-3 text-sm text-blue-900">普通用户看不到管理中心，只能使用已分配门店的日常经营页面。</p>
    <form className="grid gap-3 rounded-lg border p-4 md:grid-cols-4" onSubmit={submitUser}>
      <div><label htmlFor="new-username">新用户名</label><Input id="new-username" name="username" minLength={3} required /></div>
      <div><label htmlFor="new-password">初始密码</label><Input id="new-password" name="password" minLength={8} required type="password" /></div>
      <div><label htmlFor="new-role">角色</label><select id="new-role" className="h-9 w-full rounded-md border px-2" value={role} onChange={(event) => setRole(event.target.value as UserRole)}><option value="user">普通用户</option><option value="admin">管理员</option></select></div>
      <Button className="self-end" disabled={createUser.isPending} type="submit">{createUser.isPending ? "添加中…" : "添加用户"}</Button>
    </form>
    <ul className="divide-y rounded-lg border">{users.data?.map((user) => <UserRow key={user.id} user={user} stores={stores.data ?? []} pending={patchUser.isPending} onPatch={(body) => patchUser.mutate({ userId: user.id, body })} onHistory={() => setHistoryUserId(user.id)} />)}</ul>
    {historyUserId !== null && <section className="rounded-lg border p-3"><div className="flex justify-between"><h2 className="font-medium">用户操作历史</h2><Button size="sm" variant="ghost" onClick={() => setHistoryUserId(null)}>关闭</Button></div><ErrorMessage error={operations.error} /><ul>{operations.data?.map((entry) => <li className="border-t py-2" key={entry.id}>{entry.description}</li>)}</ul></section>}
    <section className="space-y-3 rounded-lg border p-4">
      <h2 className="font-medium">门店成员</h2>
      <label htmlFor="member-store">成员门店</label>
      <select id="member-store" className="h-9 w-full max-w-sm rounded-md border px-2" value={selectedStoreId ?? ""} onChange={(event) => { onSelectedStoreChange(event.target.value ? Number(event.target.value) : null); setMemberIds([]); }}><option value="">请选择门店</option>{stores.data?.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}</select>
      <ErrorMessage error={stores.error} /><ErrorMessage error={members.error} /><ErrorMessage error={replaceMembers.error} />
      {selectedStoreId !== null && <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); if (canSaveMembers) replaceMembers.mutate({ storeId: selectedStoreId, userIds: memberIds }); }}>
        <fieldset className="space-y-2"><legend>门店成员</legend>{users.data?.map((user) => <label className="flex items-center gap-2" key={user.id}><input checked={memberIds.includes(user.id)} onChange={(event) => setMemberIds((current) => event.target.checked ? [...current, user.id].sort((a, b) => a - b) : current.filter((id) => id !== user.id))} type="checkbox" />{user.username}</label>)}</fieldset>
        <Button disabled={!canSaveMembers || replaceMembers.isPending} type="submit">{replaceMembers.isPending ? "保存中…" : "保存成员"}</Button>
      </form>}
    </section>
  </>;
}

function UserRow({ user, stores, pending, onPatch, onHistory }: { user: AdminUser; stores: AdminStore[]; pending: boolean; onPatch: (body: UserPatchBody) => void; onHistory: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draftRole, setDraftRole] = useState<UserRole>(user.role);
  const [draftActive, setDraftActive] = useState(user.is_active);
  const [draftStoreIds, setDraftStoreIds] = useState<number[]>(user.store_ids ?? []);

  const accessibleStoreNames = user.role === "admin"
    ? "全部门店"
    : stores.filter((store) => (user.store_ids ?? []).includes(store.id)).map((store) => store.name).join("、") || "未分配门店";

  return <li className="space-y-3 p-3">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div>
        <p className="font-medium">{user.username}</p>
        <p className="text-sm text-muted-foreground">{user.role === "admin" ? "管理员" : "普通用户"} · {user.is_active ? "启用" : "停用"}</p>
        <p className="text-sm">可访问门店：{accessibleStoreNames}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button aria-label={`${user.is_active ? "停用" : "启用"}用户 ${user.username}`} disabled={pending} size="sm" variant="outline" onClick={() => onPatch({ is_active: !user.is_active })}>{user.is_active ? "停用" : "启用"}</Button>
        <Button aria-label={`编辑用户 ${user.username}`} disabled={pending} size="sm" variant="outline" onClick={() => setEditing((value) => !value)}>{editing ? "取消编辑" : "编辑"}</Button>
        <Button aria-label={`操作历史 ${user.username}`} size="sm" variant="outline" onClick={onHistory}>操作历史</Button>
      </div>
    </div>
    <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); const form = event.currentTarget; const password = String(new FormData(form).get("password")); onPatch({ password }); form.reset(); }}>
      <label className="sr-only" htmlFor={`password-${user.id}`}>新密码 {user.username}</label><Input disabled={pending} id={`password-${user.id}`} minLength={8} name="password" placeholder="新密码" required type="password" /><Button aria-label={`修改密码 ${user.username}`} disabled={pending} size="sm" type="submit">修改密码</Button>
    </form>
    {editing && <form className="space-y-3 rounded-md bg-muted/40 p-3" onSubmit={(event) => { event.preventDefault(); const password = String(new FormData(event.currentTarget).get("editor-password")); onPatch({ role: draftRole, is_active: draftActive, store_ids: draftRole === "admin" ? [] : draftStoreIds, ...(password ? { password } : {}) }); }}>
      <div><label htmlFor={`role-${user.id}`}>角色 {user.username}</label><select id={`role-${user.id}`} className="h-9 w-full rounded-md border px-2" value={draftRole} onChange={(event) => setDraftRole(event.target.value as UserRole)}><option value="user">普通用户</option><option value="admin">管理员</option></select></div>
      <label className="flex items-center gap-2"><input checked={draftActive} onChange={(event) => setDraftActive(event.target.checked)} type="checkbox" />账号启用 {user.username}</label>
      {draftRole === "user" && <fieldset className="space-y-2"><legend>可访问门店</legend>{stores.map((store) => <label className="flex items-center gap-2" key={store.id}><input aria-label={`${user.username} 可访问 ${store.name}`} checked={draftStoreIds.includes(store.id)} onChange={(event) => setDraftStoreIds((current) => event.target.checked ? [...current, store.id].sort((a, b) => a - b) : current.filter((id) => id !== store.id))} type="checkbox" />{store.name}</label>)}</fieldset>}
      <div><label htmlFor={`editor-password-${user.id}`}>重置密码 {user.username}</label><Input id={`editor-password-${user.id}`} minLength={8} name="editor-password" placeholder="留空则不修改" type="password" /></div>
      <Button aria-label={`保存用户 ${user.username}`} disabled={pending} size="sm" type="submit">保存用户</Button>
    </form>}
  </li>;
}
