import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { UserEditor, type UserDraft } from "@/admin/UserEditor";
import { api, ApiError, friendlyApiError } from "@/api/client";
import type { AdminStore, AdminUser, UserRole } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { useUnsavedChanges } from "@/navigation/UnsavedChanges";
import { accessibleStoresKey } from "@/stores/StoreProvider";

const usersKey = ["admin", "users"] as const;
const storesKey = ["admin", "stores"] as const;
type UserSelection = number | "new" | null;
type UserPatchBody = { password?: string; role: UserRole; is_active: boolean; store_ids: number[] };

function ErrorMessage({ error }: { error: Error | null }) {
  if (!error) return null;
  return <p role="alert" className="text-sm text-destructive">{friendlyApiError(error, "请求失败")}</p>;
}

export function UsersPanel() {
  const queryClient = useQueryClient();
  const [selection, setSelection] = useState<UserSelection>(null);
  const { user: actor } = useAuth();
  const { markDirty, requestTransition } = useUnsavedChanges();
  const users = useQuery({ queryKey: usersKey, queryFn: () => api<AdminUser[]>("/admin/users") });
  const stores = useQuery({ queryKey: storesKey, queryFn: () => api<AdminStore[]>("/admin/stores") });

  useEffect(() => () => markDirty(false), [markDirty]);

  async function invalidateUserData() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: usersKey, exact: true }),
      queryClient.invalidateQueries({ queryKey: accessibleStoresKey }),
    ]);
  }

  const createUser = useMutation({
    mutationFn: (input: { username: string; password: string; role: UserRole; store_ids: number[] }) =>
      api<AdminUser>("/admin/users", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: async () => {
      markDirty(false);
      await invalidateUserData();
    },
  });
  const patchUser = useMutation({
    mutationFn: ({ userId, body }: { userId: number; body: UserPatchBody }) =>
      api<AdminUser>(`/admin/users/${userId}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: async () => {
      markDirty(false);
      await invalidateUserData();
    },
  });
  const deleteUser = useMutation({
    mutationFn: (userId: number) => api<void>(`/admin/users/${userId}`, { method: "DELETE" }),
    onSuccess: async () => {
      markDirty(false);
      setSelection(null);
      await invalidateUserData();
    },
  });

  const deleteError = deleteUser.error instanceof ApiError
    && deleteUser.error.status === 409
    && deleteUser.error.detail.includes("历史")
    ? new ApiError(409, "该用户有历史记录，只能停用账号，不能永久删除。")
    : deleteUser.error;
  const selectedUser = typeof selection === "number"
    ? users.data?.find((user) => user.id === selection)
    : undefined;

  function select(next: UserSelection) {
    requestTransition(() => setSelection(next));
  }

  function submitCreate(draft: UserDraft) {
    createUser.mutate({
      username: draft.username.trim(),
      password: draft.password,
      role: draft.role,
      store_ids: draft.role === "user" ? draft.store_ids : [],
    });
  }

  function submitEdit(draft: UserDraft) {
    if (typeof selection !== "number") return;
    patchUser.mutate({
      userId: selection,
      body: {
        role: draft.role,
        is_active: draft.is_active,
        store_ids: draft.role === "user" ? draft.store_ids : [],
        ...(draft.password ? { password: draft.password } : {}),
      },
    });
  }

  function editor() {
    if (selection === "new") return <UserEditor
      mode="create"
      user={null}
      stores={stores.data ?? []}
      isOwner={actor?.is_owner === true}
      pending={createUser.isPending}
      error={createUser.error}
      onDirtyChange={markDirty}
      onSubmit={submitCreate}
    />;
    if (!selectedUser) return <p className="text-sm text-muted-foreground">请选择用户</p>;
    if (selectedUser.role === "admin" && !actor?.is_owner) {
      return <section className="rounded-lg border bg-card p-4">
        <h2 className="font-medium">{selectedUser.username}</h2>
        <p className="text-sm text-muted-foreground">管理员账号只能由最终管理员编辑</p>
      </section>;
    }
    return <UserEditor
      mode="edit"
      user={selectedUser}
      stores={stores.data ?? []}
      isOwner={actor?.is_owner === true}
      pending={patchUser.isPending || deleteUser.isPending}
      error={patchUser.error ?? deleteError}
      onDirtyChange={markDirty}
      onSubmit={submitEdit}
      onDelete={() => deleteUser.mutate(selectedUser.id)}
    />;
  }

  return <div className="space-y-4">
    <ErrorMessage error={users.error} />
    <ErrorMessage error={stores.error} />
    <div className="md:hidden">
      <label className="sr-only" htmlFor="mobile-user-selection">用户</label>
      <select
        id="mobile-user-selection"
        aria-label="用户"
        className="h-9 w-full rounded-md border border-input bg-background px-3"
        value={selection ?? ""}
        onChange={(event) => select(event.target.value === "new" ? "new" : event.target.value ? Number(event.target.value) : null)}
      >
        <option value="">请选择用户</option>
        <option value="new">新建用户</option>
        {users.data?.map((user) => <option key={user.id} value={user.id}>{user.username}</option>)}
      </select>
    </div>
    <div className="grid gap-4 md:grid-cols-[minmax(13rem,18rem)_minmax(0,1fr)]">
      <aside className="hidden space-y-3 md:block">
        <Button className="w-full" type="button" variant="outline" onClick={() => select("new")}>新建用户</Button>
        <ul className="space-y-2">
          {users.data?.map((user) => <li key={user.id}>
            <button
              type="button"
              className="w-full rounded-lg border bg-card p-3 text-left hover:bg-accent"
              aria-current={selection === user.id ? "true" : undefined}
              onClick={() => select(user.id)}
            >
              <span className="block font-medium">{user.username}</span>
              <span className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>{user.role === "admin" ? "管理员" : "普通用户"}</span>
                <span>{user.is_active ? "启用" : "停用"}</span>
                <span>{user.store_ids.length} 个门店</span>
              </span>
            </button>
          </li>)}
        </ul>
      </aside>
      <main className="min-w-0">{editor()}</main>
    </div>
  </div>;
}
