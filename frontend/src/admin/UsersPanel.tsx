import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { UserEditor, type UserDraft } from "@/admin/UserEditor";
import { api, ApiError } from "@/api/client";
import type { components } from "@/api/generated";
import type { AdminStore, AdminUser, UserRole } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { useUnsavedChanges } from "@/navigation/UnsavedChanges";
import { accessibleStoresKey } from "@/stores/StoreProvider";

const usersKey = ["admin", "users"] as const;
const storesKey = ["admin", "stores"] as const;

type UserSelection = number | "new" | null;
type UserPatchBody = components["schemas"]["UserPatch"];
type TargetState = { requestId: number; pending: boolean; error: Error | null };

function targetFor(selection: UserSelection) {
  return selection === null ? null : String(selection);
}

function ErrorMessage({ error }: { error: Error | null }) {
  if (!error) return null;
  return <p className="text-sm leading-6 text-destructive [overflow-wrap:anywhere]" role="alert">
    {error instanceof ApiError ? error.detail : "请求失败"}
  </p>;
}

export function UsersPanel() {
  const queryClient = useQueryClient();
  const { user: actor } = useAuth();
  const { markDirty, requestTransition } = useUnsavedChanges();
  const [selection, setSelection] = useState<UserSelection>(null);
  const selectionRef = useRef<UserSelection>(selection);
  const initializedSelectionRef = useRef(false);
  const mountedRef = useRef(false);
  const lifecycleGeneration = useRef(0);
  const requestIds = useRef(new Map<string, number>());
  const [requestStates, setRequestStates] = useState<Record<string, TargetState>>({});
  const [successVersions, setSuccessVersions] = useState<Record<string, number>>({});

  const users = useQuery({ queryKey: usersKey, queryFn: () => api<AdminUser[]>("/admin/users") });
  const stores = useQuery({ queryKey: storesKey, queryFn: () => api<AdminStore[]>("/admin/stores") });
  const editorOptions = useQuery({ queryKey: ["admin", "employee-editor-options"],
    queryFn: () => api<{ id: number; username: string }[]>("/admin/users/editor-options") });

  function commitSelection(next: UserSelection) {
    selectionRef.current = next;
    setSelection(next);
  }

  function select(next: UserSelection) {
    if (selectionRef.current === next) return;
    requestTransition(() => {
      if (selectionRef.current === next) return;
      commitSelection(next);
    });
  }

  function beginRequest(target: string) {
    const requestId = (requestIds.current.get(target) ?? 0) + 1;
    requestIds.current.set(target, requestId);
    setRequestStates((current) => ({
      ...current,
      [target]: { requestId, pending: true, error: null },
    }));
    return { requestId, generation: lifecycleGeneration.current };
  }

  function isLatest(target: string, requestId: number) {
    return requestIds.current.get(target) === requestId;
  }

  function isMountedTarget(target: string, generation: number) {
    return mountedRef.current
      && lifecycleGeneration.current === generation
      && targetFor(selectionRef.current) === target;
  }

  function recordSuccess(target: string) {
    setSuccessVersions((current) => ({
      ...current,
      [target]: (current[target] ?? 0) + 1,
    }));
  }

  function finishPending(target: string, requestId: number, generation: number, error: Error | null) {
    if (!isLatest(target, requestId)) return;
    setRequestStates((current) => ({
      ...current,
      [target]: { requestId, pending: false, error: isMountedTarget(target, generation) ? error : null },
    }));
  }

  async function invalidateAuthoritativeData() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: usersKey, exact: true }),
      queryClient.invalidateQueries({ queryKey: accessibleStoresKey }),
    ]);
  }

  const createUser = useMutation({
    mutationFn: ({ body }: { target: "new"; requestId: number; generation: number; body: components["schemas"]["UserCreate"] }) =>
      api<AdminUser>("/admin/users", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: async (created, { target, requestId, generation }) => {
      await invalidateAuthoritativeData();
      finishPending(target, requestId, generation, null);
      if (!isLatest(target, requestId) || !isMountedTarget(target, generation)) return;
      markDirty(false);
      recordSuccess(target);
      commitSelection(created.id);
    },
    onError: (error: Error, { target, requestId, generation }) => finishPending(target, requestId, generation, error),
  });

  const patchUser = useMutation({
    mutationFn: ({ userId, body }: { target: string; requestId: number; generation: number; userId: number; body: UserPatchBody }) =>
      api<AdminUser>(`/admin/users/${userId}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: async (_updated, { target, requestId, generation }) => {
      await invalidateAuthoritativeData();
      finishPending(target, requestId, generation, null);
      if (!isLatest(target, requestId) || !isMountedTarget(target, generation)) return;
      markDirty(false);
      recordSuccess(target);
    },
    onError: (error: Error, { target, requestId, generation }) => finishPending(target, requestId, generation, error),
  });

  const deleteUser = useMutation({
    mutationFn: ({ userId }: { target: string; requestId: number; generation: number; userId: number }) =>
      api<void>(`/admin/users/${userId}`, { method: "DELETE" }),
    onSuccess: async (_result, { target, requestId, generation }) => {
      await invalidateAuthoritativeData();
      finishPending(target, requestId, generation, null);
      if (!isLatest(target, requestId) || !isMountedTarget(target, generation)) return;
      markDirty(false);
      commitSelection(null);
    },
    onError: (error: Error, { target, requestId, generation }) => {
      const friendly = error instanceof ApiError && error.status === 409 && error.detail.includes("历史")
        ? new ApiError(409, "该用户有历史记录，只能停用账号，不能永久删除。")
        : error;
      finishPending(target, requestId, generation, friendly);
    },
  });

  const createSuccessVersion = successVersions.new ?? 0;
  const editSuccessVersion = typeof selection === "number"
    ? successVersions[String(selection)] ?? 0
    : 0;

  const selectedUser = typeof selection === "number"
    ? users.data?.find((user) => user.id === selection) ?? null
    : null;
  const mountedTarget = targetFor(selection);
  const mountedRequest = mountedTarget ? requestStates[mountedTarget] : undefined;
  const managers: AdminUser[] = [
    ...(users.data ?? []).filter((user) => user.role === "admin"),
    ...(actor?.is_owner ? [{ ...actor, username: `主管理员（${actor.username}）`,
      is_active: true, store_ids: (stores.data ?? []).map((store) => store.id), manager_id: null }] : []),
  ];

  useEffect(() => {
    if (!users.isSuccess || initializedSelectionRef.current) return;
    initializedSelectionRef.current = true;
    if (selectionRef.current === null && users.data[0]) commitSelection(users.data[0].id);
  }, [users.data, users.isSuccess]);

  useEffect(() => {
    if (typeof selection !== "number" || !users.isSuccess) return;
    if (users.data.some((user) => user.id === selection)) return;
    selectionRef.current = null;
    setSelection(null);
    markDirty(false);
  }, [markDirty, selection, users.data, users.isSuccess]);

  useEffect(() => {
    mountedRef.current = true;
    lifecycleGeneration.current += 1;
    return () => {
      mountedRef.current = false;
      lifecycleGeneration.current += 1;
      markDirty(false);
    };
  }, [markDirty]);

  function submitCreate(draft: UserDraft) {
    const target = "new";
    const { requestId, generation } = beginRequest(target);
    createUser.mutate({
      target,
      requestId,
      generation,
      body: {
        username: draft.username.trim(),
        password: draft.password,
        role: draft.role,
        store_ids: draft.store_ids,
        ...(draft.role === "user" ? { editor_ids: draft.editor_ids ?? [] } : {}),
        ...(actor?.is_owner && draft.role === "user" ? { manager_id: draft.manager_id } : {}),
      },
    });
  }

  function submitEdit(draft: UserDraft) {
    if (typeof selection !== "number") return;
    const target = String(selection);
    const { requestId, generation } = beginRequest(target);
    patchUser.mutate({
      target,
      requestId,
      generation,
      userId: selection,
      body: {
        role: draft.role,
        is_active: draft.is_active,
        store_ids: draft.store_ids,
        ...(draft.role === "user" && (actor?.is_owner || selectedUser?.can_manage_editors)
          ? { editor_ids: draft.editor_ids ?? [] } : {}),
        ...(actor?.is_owner && draft.role === "user" ? { manager_id: draft.manager_id } : {}),
        ...(draft.password ? { password: draft.password } : {}),
      },
    });
  }

  function removeUser(userId: number) {
    const target = String(userId);
    const { requestId, generation } = beginRequest(target);
    deleteUser.mutate({ target, requestId, generation, userId });
  }

  const list = users.data ?? [];

  let editor;
  if (selection === "new") {
    editor = <UserEditor
      error={mountedRequest?.error ?? null}
      isOwner={actor?.is_owner === true}
      key="new"
      mode="create"
      canManageEditors
      editorOptions={editorOptions.data ?? []}
      onDirtyChange={markDirty}
      onSubmit={submitCreate}
      pending={mountedRequest?.pending === true}
      stores={stores.data ?? []}
      managers={managers}
      successVersion={createSuccessVersion}
      user={null}
    />;
  } else if (!selectedUser) {
    editor = null;
  } else if (selectedUser.role === "admin" && !actor?.is_owner) {
    editor = <section className="min-w-0 space-y-2 rounded-xl border border-border bg-card p-4 shadow-sm [overflow-wrap:anywhere] sm:p-5">
      <h2 className="text-lg font-semibold">{selectedUser.username}</h2>
      <p className="text-sm leading-6 text-muted-foreground">从管理员账号只能由主管理员编辑</p>
    </section>;
  } else {
    editor = <UserEditor
      error={mountedRequest?.error ?? null}
      isOwner={actor?.is_owner === true}
      key={selectedUser.id}
      mode="edit"
      canManageEditors={actor?.is_owner === true || selectedUser.can_manage_editors === true}
      editorOptions={editorOptions.data ?? []}
      onDelete={() => removeUser(selectedUser.id)}
      onDirtyChange={markDirty}
      onSubmit={submitEdit}
      pending={mountedRequest?.pending === true}
      stores={stores.data ?? []}
      managers={managers}
      successVersion={editSuccessVersion}
      user={selectedUser}
    />;
  }

  return <div className="min-w-0 space-y-4">
    <ErrorMessage error={users.error} />
    <ErrorMessage error={stores.error} />
    <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(13rem,18rem)_minmax(0,1fr)] lg:grid-rows-[auto_1fr]">
      <div
        aria-label="用户列表操作"
        className="flex min-w-0 items-center gap-2 lg:col-start-1 lg:row-start-1"
        data-testid="user-panel-controls"
        role="toolbar"
      >
        <span className="hidden min-w-0 flex-1 text-sm font-medium lg:block">用户列表</span>
        <label className="min-w-0 flex-1 lg:hidden">
          <span className="sr-only">用户</span>
          <select
            aria-label="用户"
            className="h-11 w-full min-w-0 rounded-lg border border-input bg-card px-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onChange={(event) => {
              if (event.target.value) select(Number(event.target.value));
            }}
            value={typeof selection === "number" ? selection : ""}
          >
            <option hidden value="" />
            {list.map((user) => <option key={user.id} value={user.id}>{user.username}</option>)}
          </select>
        </label>
        <Button className="ml-auto shrink-0" onClick={() => select("new")} type="button">
          新建用户
        </Button>
      </div>
      <aside aria-label="用户列表" className="hidden min-w-0 lg:col-start-1 lg:row-start-2 lg:block">
        <ul className="divide-y overflow-hidden rounded-xl border border-border bg-card shadow-sm">
          {list.map((user) => <li key={user.id}>
            <button
              aria-pressed={selection === user.id}
              className={`min-h-11 w-full border-l-4 p-3 text-left transition-colors [overflow-wrap:anywhere] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-50 ${selection === user.id ? "border-l-primary bg-primary/10 text-primary" : "border-l-transparent hover:bg-accent"}`}
              onClick={() => select(user.id)}
              type="button"
            >
              <span className="block font-semibold">{user.username}</span>
              <span className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>{user.role === "admin" ? "从管理员" : "员工"}</span>
                <span>{user.is_active ? "启用" : "停用"}</span>
                <span>{user.store_ids.length} 个门店</span>
              </span>
            </button>
          </li>)}
        </ul>
      </aside>
      <main className="min-w-0 lg:col-start-2 lg:row-span-2 lg:row-start-1">{editor}</main>
    </div>
  </div>;
}
