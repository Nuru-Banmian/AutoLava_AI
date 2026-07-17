import { type FormEvent, useEffect, useRef, useState } from "react";

import { ApiError } from "@/api/client";
import type { AdminStore, AdminUser, UserRole } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export interface UserDraft {
  username: string;
  role: UserRole;
  is_active: boolean;
  store_ids: number[];
  password: string;
}

export function draftForUser(user: AdminUser): UserDraft {
  return {
    username: user.username,
    role: user.role,
    is_active: user.is_active,
    store_ids: [...user.store_ids].sort((a, b) => a - b),
    password: "",
  };
}

const createDraft: UserDraft = {
  username: "",
  role: "user",
  is_active: true,
  store_ids: [],
  password: "",
};

export interface UserEditorProps {
  mode: "create" | "edit";
  user: AdminUser | null;
  stores: AdminStore[];
  isOwner: boolean;
  pending: boolean;
  error: Error | null;
  successVersion: number;
  onDirtyChange(dirty: boolean): void;
  onSubmit(draft: UserDraft): void;
  onDelete?(): void;
}

function initialDraft(mode: UserEditorProps["mode"], user: AdminUser | null) {
  return mode === "edit" && user ? draftForUser(user) : { ...createDraft, store_ids: [] };
}

function sameDraft(first: UserDraft, second: UserDraft) {
  return first.username === second.username
    && first.role === second.role
    && first.is_active === second.is_active
    && first.password === second.password
    && first.store_ids.length === second.store_ids.length
    && first.store_ids.every((id, index) => id === second.store_ids[index]);
}

export function UserEditor({
  mode,
  user,
  stores,
  isOwner,
  pending,
  error,
  successVersion,
  onDirtyChange,
  onSubmit,
  onDelete,
}: UserEditorProps) {
  const [draft, setDraft] = useState<UserDraft>(() => initialDraft(mode, user));
  const baseline = useRef(draft);
  const appliedSuccessVersion = useRef(successVersion);

  useEffect(() => {
    onDirtyChange(!sameDraft(draft, baseline.current));
  }, [draft, onDirtyChange]);

  useEffect(() => {
    if (successVersion <= appliedSuccessVersion.current) return;
    appliedSuccessVersion.current = successVersion;
    const clean = initialDraft(mode, user);
    baseline.current = clean;
    setDraft(clean);
    onDirtyChange(false);
  }, [mode, onDirtyChange, successVersion, user]);

  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  function update(next: (current: UserDraft) => UserDraft) {
    if (pending) return;
    setDraft(next);
  }

  function toggleStore(storeId: number, checked: boolean) {
    update((current) => ({
      ...current,
      store_ids: (checked
        ? [...new Set([...current.store_ids, storeId])]
        : current.store_ids.filter((id) => id !== storeId)
      ).sort((a, b) => a - b),
    }));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    if (mode === "create" && (!draft.username.trim() || !draft.password)) return;
    onSubmit(draft);
  }

  const assignedUnavailable = draft.store_ids
    .map((id) => stores.find((store) => store.id === id) ?? id)
    .filter((storeOrId) => typeof storeOrId === "number" || !storeOrId.is_active);

  return <section className="rounded-lg border bg-card p-4">
    <h2 className="text-lg font-semibold">{mode === "create" ? "新建用户" : `编辑 ${user?.username ?? ""}`}</h2>
    <form className="mt-4 space-y-4" onSubmit={submit}>
      {mode === "create" ? <div className="space-y-1">
        <label htmlFor="user-username">用户名</label>
        <Input
          disabled={pending}
          id="user-username"
          minLength={3}
          onChange={(event) => update((current) => ({ ...current, username: event.target.value }))}
          required
          value={draft.username}
        />
      </div> : <p className="text-sm text-muted-foreground">用户名：{draft.username}</p>}

      <div className="space-y-1">
        <label htmlFor="user-role">角色</label>
        <select
          className="h-9 w-full rounded-md border bg-background px-2 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={pending}
          id="user-role"
          onChange={(event) => update((current) => ({ ...current, role: event.target.value as UserRole }))}
          value={draft.role}
        >
          <option value="user">普通用户</option>
          {isOwner && <option value="admin">管理员</option>}
        </select>
      </div>

      {mode === "edit" && <label className="flex items-center gap-2">
        <input
          checked={draft.is_active}
          disabled={pending}
          onChange={(event) => update((current) => ({ ...current, is_active: event.target.checked }))}
          type="checkbox"
        />
        账号启用
      </label>}

      {draft.role === "user" && <fieldset className="space-y-2">
        <legend className="font-medium">可访问门店</legend>
        {stores.filter((store) => store.is_active).map((store) => <label className="flex items-center gap-2" key={store.id}>
          <input
            checked={draft.store_ids.includes(store.id)}
            disabled={pending}
            onChange={(event) => toggleStore(store.id, event.target.checked)}
            type="checkbox"
          />
          {store.name}
        </label>)}
        {assignedUnavailable.map((storeOrId) => {
          const id = typeof storeOrId === "number" ? storeOrId : storeOrId.id;
          const label = typeof storeOrId === "number"
            ? `未知门店 #${storeOrId}（不可用）`
            : `${storeOrId.name}（已停用，不可用）`;
          return <label className="flex items-center gap-2 text-muted-foreground" key={id}>
            <input
              checked={draft.store_ids.includes(id)}
              disabled={pending}
              onChange={(event) => toggleStore(id, event.target.checked)}
              type="checkbox"
            />
            {label}
          </label>;
        })}
        {stores.filter((store) => store.is_active).length === 0 && assignedUnavailable.length === 0
          && <p className="text-sm text-muted-foreground">暂无可用门店</p>}
      </fieldset>}

      <div className="space-y-1">
        <label htmlFor="user-password">{mode === "create" ? "初始密码" : "重置密码（可选）"}</label>
        <Input
          disabled={pending}
          id="user-password"
          minLength={8}
          onChange={(event) => update((current) => ({ ...current, password: event.target.value }))}
          placeholder={mode === "edit" ? "留空则不修改" : undefined}
          required={mode === "create"}
          type="password"
          value={draft.password}
        />
      </div>

      {error && <p className="text-sm text-destructive" role="alert">
        {error instanceof ApiError ? error.detail : "请求失败"}
      </p>}

      <div className="flex items-center justify-between gap-3" data-testid="user-editor-actions">
        <Button disabled={pending} type="submit">
          {mode === "create" ? "添加用户" : "保存用户"}
        </Button>
        {mode === "edit" && onDelete && <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button disabled={pending} type="button" variant="destructive">永久删除</Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>永久删除用户？</AlertDialogTitle>
              <AlertDialogDescription>此操作不可恢复。确定要永久删除“{user?.username}”吗？</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction onClick={() => { if (!pending) onDelete(); }}>确认永久删除</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>}
      </div>
    </form>
  </section>;
}
