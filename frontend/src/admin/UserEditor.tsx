import { type FormEvent, useEffect, useRef, useState } from "react";

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
  onDirtyChange(dirty: boolean): void;
  onSubmit(draft: UserDraft): void;
  onDelete?(): void;
}

function initialDraft(mode: UserEditorProps["mode"], user: AdminUser | null) {
  return mode === "edit" && user ? draftForUser(user) : { ...createDraft };
}

function sameDraft(left: UserDraft, right: UserDraft) {
  return left.username === right.username
    && left.role === right.role
    && left.is_active === right.is_active
    && left.password === right.password
    && left.store_ids.length === right.store_ids.length
    && left.store_ids.every((id, index) => id === right.store_ids[index]);
}

export function UserEditor({ mode, user, stores, isOwner, pending, error, onDirtyChange, onSubmit, onDelete }: UserEditorProps) {
  const [draft, setDraft] = useState<UserDraft>(() => initialDraft(mode, user));
  const baseline = useRef(initialDraft(mode, user));
  const submitted = useRef(false);
  const wasPending = useRef(false);
  const identity = mode === "edit" ? user?.id : "new";

  useEffect(() => {
    const next = initialDraft(mode, user);
    baseline.current = next;
    setDraft(next);
    submitted.current = false;
    wasPending.current = false;
    onDirtyChange(false);
  }, [identity, mode, onDirtyChange]);

  useEffect(() => {
    if (pending) wasPending.current = true;
    if (!pending && wasPending.current && submitted.current && !error) {
      const next = mode === "create"
        ? { ...createDraft }
        : { ...draft, password: "" };
      baseline.current = next;
      setDraft(next);
      submitted.current = false;
      wasPending.current = false;
      onDirtyChange(false);
    }
  }, [draft, error, mode, onDirtyChange, pending]);

  function update(next: UserDraft) {
    const normalized = { ...next, store_ids: [...next.store_ids].sort((a, b) => a - b) };
    setDraft(normalized);
    onDirtyChange(!sameDraft(normalized, baseline.current));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === "create" && (!draft.username.trim() || !draft.password)) return;
    submitted.current = true;
    onSubmit(draft);
  }

  const activeStores = stores.filter((store) => store.is_active);

  return <section className="space-y-5 rounded-lg border bg-card p-4">
    <h2 className="text-lg font-semibold">{mode === "create" ? "新建用户" : `编辑 ${user?.username ?? ""}`}</h2>
    <form className="space-y-4" onSubmit={submit}>
      {mode === "create" ? <div className="space-y-1">
        <label htmlFor="user-username">用户名</label>
        <Input id="user-username" minLength={3} required value={draft.username} onChange={(event) => update({ ...draft, username: event.target.value })} />
      </div> : <p className="text-sm"><span className="text-muted-foreground">用户名：</span>{draft.username}</p>}

      <div className="space-y-1">
        <label htmlFor="user-role">角色</label>
        <select id="user-role" className="h-9 w-full rounded-md border border-input bg-background px-3" value={draft.role} onChange={(event) => update({ ...draft, role: event.target.value as UserRole })}>
          <option value="user">普通用户</option>
          {isOwner && <option value="admin">管理员</option>}
        </select>
      </div>

      {mode === "edit" && <label className="flex items-center gap-2">
        <input checked={draft.is_active} type="checkbox" onChange={(event) => update({ ...draft, is_active: event.target.checked })} />
        账号启用
      </label>}

      {draft.role === "user" && <fieldset className="space-y-2">
        <legend className="font-medium">可访问门店</legend>
        {activeStores.length === 0 && <p className="text-sm text-muted-foreground">暂无可分配门店</p>}
        {activeStores.map((store) => <label className="flex items-center gap-2" key={store.id}>
          <input
            checked={draft.store_ids.includes(store.id)}
            type="checkbox"
            onChange={(event) => update({
              ...draft,
              store_ids: event.target.checked
                ? [...draft.store_ids, store.id]
                : draft.store_ids.filter((id) => id !== store.id),
            })}
          />
          {store.name}
        </label>)}
      </fieldset>}

      <div className="space-y-1">
        <label htmlFor="user-password">{mode === "create" ? "初始密码" : "重置密码（可选）"}</label>
        <Input id="user-password" minLength={8} required={mode === "create"} type="password" value={draft.password} onChange={(event) => update({ ...draft, password: event.target.value })} />
      </div>

      {error && <p role="alert" className="text-sm text-destructive">{error.message || "请求失败"}</p>}
      <Button disabled={pending} type="submit">{pending ? "保存中…" : mode === "create" ? "添加用户" : "保存用户"}</Button>
    </form>

    {mode === "edit" && onDelete && <section aria-label="危险操作" className="space-y-2 border-t pt-4">
      <p className="text-sm text-muted-foreground">永久删除后无法恢复。</p>
      <AlertDialog>
        <AlertDialogTrigger asChild><Button disabled={pending} type="button" variant="destructive">永久删除</Button></AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认永久删除用户？</AlertDialogTitle>
            <AlertDialogDescription>此操作无法恢复。确定删除“{user?.username}”吗？</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete}>确认删除</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>}
  </section>;
}
