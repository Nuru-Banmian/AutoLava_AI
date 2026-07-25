import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronLeft, ChevronRight, Ellipsis, MoreHorizontal } from "lucide-react";
import { Link } from "react-router-dom";

import { api, ApiError, friendlyApiError } from "@/api/client";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useStore } from "@/stores/StoreProvider";

interface SettlementWorkspace {
  store_id: number;
  store_name: string;
  company_settlement_enabled: true;
}

interface SettlementCompany {
  id: number;
  name: string;
  is_active: boolean;
}

interface SettlementRecord {
  id: number;
  company_id: number;
  company_name: string;
  opening_month: string;
  amount: number;
  status: "pending" | "confirmed";
  revision: number;
  created_at: string;
}

interface SettlementMonth {
  opening_month: string;
  records: SettlementRecord[];
  daily_ledger_revenue: number;
  confirmed_settlement_income: number;
  pending_amount: number;
  monthly_total: number;
}

export function monthInTimezone(timezone: string, now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone, year: "numeric", month: "2-digit",
  }).formatToParts(now);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}`;
}

function shiftMonth(value: string, offset: number) {
  const [year, month] = value.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1 + offset, 1));
  return `${shifted.getUTCFullYear()}-${String(shifted.getUTCMonth() + 1).padStart(2, "0")}`;
}

function euro(value: number) {
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value);
}

const MAX_SETTLEMENT_AMOUNT = 9_999_999_999;
const recordGridColumns = "md:grid-cols-[minmax(0,1fr)_8rem_7rem_11rem]";

function validAmount(value: string) {
  const amount = Number(value);
  return /^\d+$/.test(value) && Number.isSafeInteger(amount) && amount > 0 && amount <= MAX_SETTLEMENT_AMOUNT;
}

interface CompanyMutation {
  storeId: number;
  path: string;
  method: string;
  body?: string;
  retry: () => void;
}

interface RecordTarget {
  storeId: number;
  month: string;
  recordId: number;
  revision: number;
}

interface RecordEditVariables extends RecordTarget {
  companyId: number;
  amount: number;
}

type RecordTransitionKind = "confirm" | "revoke";

interface RecordTransition extends RecordTarget { kind: RecordTransitionKind }

const recordTransitionConfig = {
  confirm: {
    path: "confirm",
    targetStatus: "confirmed",
    successMessage: "开票记录已确认到账",
    syncMessage: "记录状态已同步：已确认到账",
    errorMessage: "到账确认失败，请重试",
    dialogTitle: "确认整笔到账？",
    actionLabel: "确认到账",
    variant: "default",
    description: (record: SettlementRecord) => `${record.company_name} 的 ${euro(record.amount)} 将全部计入 ${record.opening_month} 的月度总收入，不记录单独到账日期。`,
  },
  revoke: {
    path: "revoke-confirmation",
    targetStatus: "pending",
    successMessage: "已撤销开票记录到账确认",
    syncMessage: "记录状态已同步：待到账",
    errorMessage: "撤销到账确认失败，请重试",
    dialogTitle: "撤销到账确认？",
    actionLabel: "确认撤销到账确认",
    variant: "outline",
    description: (record: SettlementRecord) => `${record.company_name} 的 ${euro(record.amount)} 将从 ${record.opening_month} 的月度总收入中扣除，并恢复为可修改、可删除的待到账记录。`,
  },
} as const;

function canonicalConflictRecord(error: unknown): SettlementRecord | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const response = error.responseBody;
  if (typeof response !== "object" || response === null || !("detail" in response)) return null;
  const detail = response.detail;
  if (typeof detail !== "object" || detail === null || !("current_record" in detail)) return null;
  const current = detail.current_record;
  if (
    typeof current !== "object" || current === null
    || !("id" in current) || typeof current.id !== "number"
    || !("revision" in current) || typeof current.revision !== "number"
  ) return null;
  return current as SettlementRecord;
}

function RecordActionsMenu({ record, disabled, onEdit, onDelete, onRevoke }: {
  record: SettlementRecord;
  disabled: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onRevoke: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const closeFromOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeFromOutside);
    return () => document.removeEventListener("pointerdown", closeFromOutside);
  }, [open]);

  const closeAndFocusTrigger = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };
  const openFromKeyboard = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!["Enter", " ", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    setOpen(true);
  };
  const navigateMenu = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
    const currentIndex = items.indexOf(document.activeElement as HTMLElement);
    let nextIndex: number | null = null;
    if (event.key === "ArrowDown") nextIndex = (currentIndex + 1) % items.length;
    if (event.key === "ArrowUp") nextIndex = (currentIndex - 1 + items.length) % items.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = items.length - 1;
    if (event.key === "Escape") {
      event.preventDefault();
      closeAndFocusTrigger();
      return;
    }
    if (nextIndex !== null) {
      event.preventDefault();
      items[nextIndex]?.focus();
    }
  };
  const runAction = (action: () => void) => {
    setOpen(false);
    action();
  };

  return <div className="relative" ref={rootRef}>
    <Button
      aria-expanded={open}
      aria-haspopup="menu"
      aria-label={`${record.company_name}开票记录更多操作`}
      disabled={disabled}
      onClick={() => setOpen((value) => !value)}
      onKeyDown={openFromKeyboard}
      ref={triggerRef}
      size="icon"
      type="button"
      variant="outline"
    >
      <Ellipsis aria-hidden="true" />
    </Button>
    {open && <div
      aria-label={`${record.company_name}开票记录操作`}
      className="absolute right-0 top-full z-20 mt-1 min-w-44 rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
      onKeyDown={navigateMenu}
      ref={menuRef}
      role="menu"
    >
      {record.status === "pending" ? <>
        <button aria-label={`编辑${record.company_name}开票记录`} className="flex w-full rounded-sm px-2 py-2 text-left text-sm outline-none hover:bg-accent focus:bg-accent" onClick={() => runAction(onEdit)} role="menuitem" type="button">
          编辑
          <span className="sr-only">{record.company_name}开票记录</span>
        </button>
        <button aria-label={`删除${record.company_name}开票记录`} className="flex w-full rounded-sm px-2 py-2 text-left text-sm text-destructive outline-none hover:bg-destructive/10 focus:bg-destructive/10" onClick={() => runAction(onDelete)} role="menuitem" type="button">
          删除
          <span className="sr-only">{record.company_name}开票记录</span>
        </button>
      </> : <button aria-label={`撤销${record.company_name}开票记录到账确认`} className="flex w-full rounded-sm px-2 py-2 text-left text-sm outline-none hover:bg-accent focus:bg-accent" onClick={() => runAction(onRevoke)} role="menuitem" type="button">
        撤销到账确认
        <span className="sr-only">{record.company_name}开票记录</span>
      </button>}
    </div>}
  </div>;
}

function CompanyActionMenu({ company, archived, busy, onRename, onLifecycle, onDelete }: {
  company: SettlementCompany;
  archived: boolean;
  busy: boolean;
  onRename: () => void;
  onLifecycle: () => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    const closeWhenFocusLeaves = (event: FocusEvent) => {
      const target = event.target;
      if (target instanceof Node && !menuRef.current?.contains(target) && target !== triggerRef.current) {
        setOpen(false);
      }
    };
    document.addEventListener("focusin", closeWhenFocusLeaves);
    return () => document.removeEventListener("focusin", closeWhenFocusLeaves);
  }, [open]);

  const closeAndRun = (action: () => void) => {
    setOpen(false);
    triggerRef.current?.focus();
    action();
  };
  const handleMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? []);
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (event.key === "Tab") {
      setOpen(false);
      return;
    }
    let next = current;
    if (event.key === "ArrowDown") next = (current + 1) % items.length;
    else if (event.key === "ArrowUp") next = (current - 1 + items.length) % items.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = items.length - 1;
    else return;
    event.preventDefault();
    items[next]?.focus();
  };

  return <div className="relative shrink-0">
    <Button
      aria-expanded={open}
      aria-haspopup="menu"
      aria-label={`${company.name}更多操作`}
      disabled={busy}
      onClick={() => setOpen((current) => !current)}
      onKeyDown={(event) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          setOpen(true);
        }
      }}
      ref={triggerRef}
      size="icon"
      type="button"
      variant="ghost"
    >
      <MoreHorizontal aria-hidden="true" />
    </Button>
    {open && <div
      aria-label={`${company.name}操作`}
      className="absolute right-0 top-full z-20 mt-1 grid w-44 rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
      onKeyDown={handleMenuKeyDown}
      ref={menuRef}
      role="menu"
    >
      <button aria-label={`重命名${company.name}`} className="rounded-sm px-2 py-2 text-left text-sm outline-none hover:bg-accent focus:bg-accent" onClick={() => closeAndRun(onRename)} role="menuitem" type="button">
        重命名
      </button>
      <button aria-label={archived ? `恢复${company.name}` : `归档${company.name}`} className="rounded-sm px-2 py-2 text-left text-sm outline-none hover:bg-accent focus:bg-accent" onClick={() => closeAndRun(onLifecycle)} role="menuitem" type="button">
        {archived ? "恢复" : "归档"}
      </button>
      <button aria-label={`永久删除${company.name}`} className="rounded-sm px-2 py-2 text-left text-sm text-destructive outline-none hover:bg-destructive/10 focus:bg-destructive/10" onClick={() => closeAndRun(onDelete)} role="menuitem" type="button">
        永久删除
      </button>
    </div>}
  </div>;
}

function CompanyList({ companies, archived, busy, onRename, onLifecycle, onDelete }: {
  companies: SettlementCompany[];
  archived: boolean;
  busy: boolean;
  onRename: (company: SettlementCompany, name: string) => Promise<boolean>;
  onLifecycle: (company: SettlementCompany) => Promise<boolean>;
  onDelete: (company: SettlementCompany) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState<number | null>(null);
  const [names, setNames] = useState<Record<number, string>>({});
  const listRef = useRef<HTMLUListElement>(null);
  const runRemovingAction = async (company: SettlementCompany, action: (company: SettlementCompany) => Promise<boolean>) => {
    const companyIndex = companies.findIndex((candidate) => candidate.id === company.id);
    await action(company);
    requestAnimationFrame(() => {
      const triggers = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>('button[aria-haspopup="menu"]') ?? []);
      const nextTrigger = triggers[Math.min(Math.max(companyIndex, 0), triggers.length - 1)];
      if (nextTrigger) nextTrigger.focus();
      else listRef.current?.closest<HTMLElement>('[role="region"]')?.focus();
    });
  };
  if (!companies.length) return <p className="px-1 py-3 text-sm text-muted-foreground">{archived ? "暂无归档公司" : "暂无使用中的公司"}</p>;
  return <ul className="grid gap-1" ref={listRef}>
    {companies.map((company) => <li className="relative min-w-0 rounded-md border px-2 py-1" key={company.id}>
      {editing === company.id ? <form className="flex min-w-0 flex-wrap gap-2" onSubmit={(event) => {
        event.preventDefault();
        void onRename(company, names[company.id] ?? company.name).then((saved) => {
          if (saved) setEditing(null);
        });
      }}>
        <label className="min-w-0 flex-1">
          <span className="sr-only">重命名{company.name}</span>
          <Input autoFocus maxLength={120} value={names[company.id] ?? company.name} onChange={(event) => setNames((current) => ({ ...current, [company.id]: event.target.value }))} />
        </label>
        <Button disabled={busy} type="submit">保存名称</Button>
        <Button onClick={() => setEditing(null)} type="button" variant="outline">取消</Button>
      </form> : <div className="flex min-w-0 items-center justify-between gap-2">
        <span className="min-w-0 truncate text-sm font-medium" title={company.name}>{company.name}</span>
        <CompanyActionMenu
          archived={archived}
          busy={busy}
          company={company}
          onDelete={() => {
            if (window.confirm(`确定永久删除结算公司“${company.name}”吗？此操作无法撤销。`)) void runRemovingAction(company, onDelete);
          }}
          onLifecycle={() => { void runRemovingAction(company, onLifecycle); }}
          onRename={() => {
            setNames((current) => ({ ...current, [company.id]: current[company.id] ?? company.name }));
            setEditing(company.id);
          }}
        />
      </div>}
    </li>)}
  </ul>;
}

export function CompanySettlementPage() {
  const { selected, isLoading } = useStore();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [failedAction, setFailedAction] = useState<(() => void) | null>(null);
  const [month, setMonth] = useState(() => selected ? monthInTimezone(selected.timezone) : "");
  const [companyId, setCompanyId] = useState("");
  const [amount, setAmount] = useState("");
  const [recordError, setRecordError] = useState("");
  const [recordMessage, setRecordMessage] = useState("");
  const [editingRecord, setEditingRecord] = useState<SettlementRecord | null>(null);
  const [editCompanyId, setEditCompanyId] = useState("");
  const [editAmount, setEditAmount] = useState("");
  const [recordToDelete, setRecordToDelete] = useState<SettlementRecord | null>(null);
  const [companyManagementStoreId, setCompanyManagementStoreId] = useState<number | null>(null);
  const [companyTab, setCompanyTab] = useState<"active" | "archived">("active");
  const [recordTransition, setRecordTransition] = useState<{
    record: SettlementRecord;
    kind: RecordTransitionKind;
  } | null>(null);
  const enabled = selected?.company_settlement_enabled === true;
  const companyManagementOpen = companyManagementStoreId === selected?.id;
  const currentMonth = selected ? monthInTimezone(selected.timezone) : "";
  const workspace = useQuery({
    queryKey: ["settlements", selected?.id],
    queryFn: () => api<SettlementWorkspace>(`/settlements/${selected!.id}`),
    enabled: Boolean(selected && enabled),
  });
  const active = useQuery({
    queryKey: ["settlement-companies", selected?.id, "active"],
    queryFn: () => api<SettlementCompany[]>(`/settlements/${selected!.id}/companies`),
    enabled: Boolean(selected && enabled && workspace.data),
  });
  const archived = useQuery({
    queryKey: ["settlement-companies", selected?.id, "archived"],
    queryFn: () => api<SettlementCompany[]>(`/settlements/${selected!.id}/companies?archived=true`),
    enabled: Boolean(selected && enabled && workspace.data && companyManagementOpen),
  });
  const monthSummary = useQuery({
    queryKey: ["settlement-month", selected?.id, month],
    queryFn: () => api<SettlementMonth>(`/settlements/${selected!.id}/months/${month}`),
    enabled: Boolean(selected && enabled && workspace.data && month),
  });
  const refresh = async (storeId: number) => {
    await queryClient.invalidateQueries({ queryKey: ["settlement-companies", storeId] });
  };
  const companyMutation = useMutation({
    mutationFn: ({ path, method, body }: CompanyMutation) => api<SettlementCompany | void>(path, { method, body }),
    onSuccess: async (_result, variables) => {
      if (selected?.id === variables.storeId) {
        setMessage("");
        setFailedAction(null);
        if (variables.method === "POST" && variables.path.endsWith("/companies")) setName("");
      }
      await refresh(variables.storeId);
    },
    onError: (error, variables) => {
      if (selected?.id !== variables.storeId) return;
      setMessage(friendlyApiError(error, "操作失败，请重试"));
      setFailedAction(() => variables.retry);
    },
  });
  const recordMutation = useMutation({
    mutationFn: (variables: { storeId: number; month: string; companyId: number; amount: number }) =>
      api<SettlementRecord>(`/settlements/${variables.storeId}/records`, {
        method: "POST",
        body: JSON.stringify({ company_id: variables.companyId, opening_month: variables.month, amount: variables.amount }),
      }),
    onSuccess: async (_record, variables) => {
      if (selected?.id === variables.storeId) {
        setAmount("");
        setRecordError("");
      }
      await queryClient.invalidateQueries({ queryKey: ["settlement-month", variables.storeId, variables.month] });
    },
    onError: (error, variables) => {
      if (selected?.id === variables.storeId) setRecordError(friendlyApiError(error, "开票记录保存失败，请重试"));
    },
  });
  const editRecordMutation = useMutation({
    mutationFn: (variables: RecordEditVariables) => api<SettlementRecord>(
      `/settlements/${variables.storeId}/records/${variables.recordId}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          company_id: variables.companyId,
          amount: variables.amount,
          revision: variables.revision,
        }),
      },
    ),
    onSuccess: async (_record, variables) => {
      if (selected?.id === variables.storeId) {
        setEditingRecord(null);
        setRecordError("");
        setRecordMessage("开票记录已修改");
      }
      await queryClient.invalidateQueries({ queryKey: ["settlement-month", variables.storeId, variables.month] });
    },
    onError: async (error, variables) => {
      if (selected?.id === variables.storeId) {
        const current = canonicalConflictRecord(error);
        if (current?.id === variables.recordId) setEditingRecord(current);
        setRecordError(friendlyApiError(error, "开票记录修改失败，请重试"));
        setRecordMessage("");
      }
      await queryClient.invalidateQueries({ queryKey: ["settlement-month", variables.storeId, variables.month] });
    },
  });
  const deleteRecordMutation = useMutation({
    mutationFn: (variables: RecordTarget) => api<void>(
      `/settlements/${variables.storeId}/records/${variables.recordId}`,
      { method: "DELETE", body: JSON.stringify({ revision: variables.revision }) },
    ),
    onSuccess: async (_result, variables) => {
      if (selected?.id === variables.storeId) {
        setRecordToDelete(null);
        setRecordError("");
        setRecordMessage("开票记录已永久删除");
      }
      await queryClient.invalidateQueries({ queryKey: ["settlement-month", variables.storeId, variables.month] });
    },
    onError: async (error, variables) => {
      if (selected?.id === variables.storeId) {
        const current = canonicalConflictRecord(error);
        if (current?.id === variables.recordId) setRecordToDelete(current);
        setRecordError(friendlyApiError(error, "开票记录删除失败，请重试"));
        setRecordMessage("");
      }
      await queryClient.invalidateQueries({ queryKey: ["settlement-month", variables.storeId, variables.month] });
    },
  });
  const transitionRecordMutation = useMutation({
    mutationFn: (variables: RecordTransition) => {
      const config = recordTransitionConfig[variables.kind];
      return api<SettlementRecord>(
        `/settlements/${variables.storeId}/records/${variables.recordId}/${config.path}`,
        { method: "POST", body: JSON.stringify({ revision: variables.revision }) },
      );
    },
    onSuccess: async (_record, variables) => {
      if (selected?.id === variables.storeId) {
        setRecordTransition(null);
        setRecordError("");
        setRecordMessage(recordTransitionConfig[variables.kind].successMessage);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["settlement-month", variables.storeId, variables.month] }),
        queryClient.invalidateQueries({ queryKey: ["charts", variables.storeId] }),
      ]);
    },
    onError: async (error, variables) => {
      const config = recordTransitionConfig[variables.kind];
      const current = canonicalConflictRecord(error);
      const targetReached = current?.id === variables.recordId
        && current.status === config.targetStatus;
      if (selected?.id === variables.storeId) {
        if (targetReached) {
          setRecordTransition(null);
          setRecordError("");
          setRecordMessage(config.syncMessage);
        } else {
          if (current?.id === variables.recordId) {
            setRecordTransition({ record: current, kind: variables.kind });
          }
          setRecordError(friendlyApiError(error, config.errorMessage));
          setRecordMessage("");
        }
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["settlement-month", variables.storeId, variables.month] }),
        ...(targetReached
          ? [queryClient.invalidateQueries({ queryKey: ["charts", variables.storeId] })]
          : []),
      ]);
    },
  });
  useEffect(() => {
    setName("");
    setMessage("");
    setFailedAction(null);
    setMonth(selected ? monthInTimezone(selected.timezone) : "");
    setCompanyId("");
    setAmount("");
    setRecordError("");
    setRecordMessage("");
    setEditingRecord(null);
    setEditCompanyId("");
    setEditAmount("");
    setRecordToDelete(null);
    setCompanyManagementStoreId(null);
    setCompanyTab("active");
    setRecordTransition(null);
    companyMutation.reset();
    recordMutation.reset();
    editRecordMutation.reset();
    deleteRecordMutation.reset();
    transitionRecordMutation.reset();
  }, [selected?.id]);

  const openRecordEditor = (record: SettlementRecord) => {
    setEditingRecord(record);
    setEditCompanyId(String(record.company_id));
    setEditAmount(String(record.amount));
    setRecordError("");
    setRecordMessage("");
    editRecordMutation.reset();
  };

  const openRecordTransition = (record: SettlementRecord, kind: RecordTransitionKind) => {
    setRecordError("");
    setRecordMessage("");
    transitionRecordMutation.reset();
    setRecordTransition({ record, kind });
  };

  const submitRecordEdit = () => {
    if (!selected || !editingRecord || !validAmount(editAmount) || !editCompanyId) return;
    editRecordMutation.mutate({
      storeId: selected.id,
      month: editingRecord.opening_month,
      recordId: editingRecord.id,
      companyId: Number(editCompanyId),
      amount: Number(editAmount),
      revision: editingRecord.revision,
    });
  };

  const submitRecordDelete = () => {
    if (!selected || !recordToDelete) return;
    deleteRecordMutation.mutate({
      storeId: selected.id,
      month: recordToDelete.opening_month,
      recordId: recordToDelete.id,
      revision: recordToDelete.revision,
    });
  };
  const submitRecordTransition = () => {
    if (!selected || !recordTransition) return;
    transitionRecordMutation.mutate({
      storeId: selected.id,
      month: recordTransition.record.opening_month,
      recordId: recordTransition.record.id,
      revision: recordTransition.record.revision,
      kind: recordTransition.kind,
    });
  };
  const submitCreate = (storeId: number, submittedName: string) => {
    const retry = () => submitCreate(storeId, submittedName);
    companyMutation.mutate({
      storeId,
      path: `/settlements/${storeId}/companies`,
      method: "POST",
      body: JSON.stringify({ name: submittedName }),
      retry,
    });
  };
  const create = (event?: FormEvent) => {
    event?.preventDefault();
    if (!selected) return;
    submitCreate(selected.id, name);
  };
  const runCompanyAction = async (storeId: number, path: string, method: string, body?: object) => {
    const retry = () => void runCompanyAction(storeId, path, method, body);
    try {
      await companyMutation.mutateAsync({ storeId, path, method, body: body ? JSON.stringify(body) : undefined, retry });
      return true;
    } catch {
      return false;
    }
  };

  if (isLoading) return <p role="status">正在加载门店…</p>;
  if (!selected) return <p role="alert">没有可访问的门店。</p>;
  if (!enabled) {
    return <section className="space-y-3" aria-labelledby="settlement-title">
      <h1 id="settlement-title" className="text-2xl font-semibold">公司结算</h1>
      <p role="alert">当前门店未启用公司结算。</p>
      <Link className="text-primary underline" to="/">返回首页</Link>
    </section>;
  }
  if (workspace.error) return <div className="space-y-3" role="alert">
    <p>{friendlyApiError(workspace.error, "公司结算加载失败")}</p>
    <Button onClick={() => void workspace.refetch()} type="button" variant="outline">重试公司结算</Button>
  </div>;

  return <section className="grid min-w-0 gap-6" aria-labelledby="settlement-title">
    <header className="flex min-w-0 flex-wrap items-end justify-between gap-4">
      <div>
        <h1 id="settlement-title" className="text-2xl font-semibold">公司结算</h1>
        <p className="mt-1 text-sm text-muted-foreground">按开票月份登记记录并跟踪到账状态。</p>
      </div>
      {workspace.data && <div className="flex min-w-0 items-end gap-2" role="group" aria-label="月份导航">
        <Button aria-label="前一月" onClick={() => setMonth((value) => shiftMonth(value, -1))} size="icon" type="button" variant="outline">
          <ChevronLeft aria-hidden="true" />
        </Button>
        <label className="grid min-w-0 gap-1 text-sm font-medium">
          开票月份
          <Input aria-label="开票月份" className="min-w-0" max={currentMonth} onChange={(event) => setMonth(event.target.value)} required type="month" value={month} />
        </label>
        <Button aria-label="后一月" disabled={!month || month >= currentMonth} onClick={() => setMonth((value) => shiftMonth(value, 1))} size="icon" type="button" variant="outline">
          <ChevronRight aria-hidden="true" />
        </Button>
      </div>}
    </header>
    {workspace.data && <>
      <section className="grid gap-4 rounded-xl border bg-card p-4 shadow-sm" aria-labelledby="monthly-summary-title">
        <h2 className="text-lg font-semibold" id="monthly-summary-title">月度汇总</h2>
        {monthSummary.isLoading ? <p role="status">正在加载月份记录…</p> : monthSummary.error ? <div role="alert"><p>{friendlyApiError(monthSummary.error, "月份记录加载失败")}</p><Button onClick={() => void monthSummary.refetch()} type="button" variant="outline">重试月份记录</Button></div> : monthSummary.data && <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl bg-muted/50 p-3"><dt className="text-sm text-muted-foreground">日常营业额</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{euro(monthSummary.data.daily_ledger_revenue)}</dd></div>
          <div className="rounded-xl bg-muted/50 p-3"><dt className="text-sm text-muted-foreground">已确认公司结算</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{euro(monthSummary.data.confirmed_settlement_income)}</dd></div>
          <div className="rounded-xl bg-muted/50 p-3"><dt className="text-sm text-muted-foreground">待到账金额</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{euro(monthSummary.data.pending_amount)}</dd></div>
          <div className="rounded-xl bg-muted/50 p-3"><dt className="text-sm text-muted-foreground">月度总收入</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{euro(monthSummary.data.monthly_total)}</dd></div>
        </dl>}
      </section>
      <section className="grid gap-4 rounded-xl border bg-card p-4 shadow-sm" aria-labelledby="record-registration-title">
        <h2 className="text-lg font-semibold" id="record-registration-title">登记开票记录</h2>
        <form aria-labelledby="record-registration-title" className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(12rem,1fr)_minmax(12rem,1fr)_auto]" onSubmit={(event) => {
          event.preventDefault();
          if (!selected || !month || !companyId || !validAmount(amount)) return;
          setRecordError("");
          recordMutation.mutate({ storeId: selected.id, month, companyId: Number(companyId), amount: Number(amount) });
        }}>
          <label className="grid min-w-0 gap-1 text-sm font-medium">
            结算公司
            <select aria-label="结算公司" className="h-9 min-w-0 rounded-md border border-input bg-transparent px-3 text-sm" onChange={(event) => setCompanyId(event.target.value)} required value={companyId}>
              <option value="">请选择使用中的结算公司</option>
              {(active.data ?? []).map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium">
            金额（整数欧元）
            <Input aria-label="金额（整数欧元）" inputMode="numeric" max={MAX_SETTLEMENT_AMOUNT} min="1" onChange={(event) => setAmount(event.target.value)} pattern="[0-9]+" required step="1" type="number" value={amount} />
          </label>
          <div className="flex items-end">
            <Button className="w-full lg:w-auto" disabled={recordMutation.isPending || !month || !companyId || !validAmount(amount)} type="submit">登记待到账记录</Button>
          </div>
        </form>
        {recordError && <div role="alert">{recordError}<Button className="ml-2" disabled={recordMutation.isPending} onClick={() => {
          if (recordMutation.isError && selected && month && companyId && validAmount(amount)) recordMutation.mutate({ storeId: selected.id, month, companyId: Number(companyId), amount: Number(amount) });
        }} type="button" variant="outline">重试保存</Button></div>}
      </section>
      <section className="grid gap-4 rounded-xl border bg-card p-4 shadow-sm" aria-labelledby="records-title">
        <div>
          <h2 className="text-lg font-semibold" id="records-title">开票记录列表</h2>
          <p className="mt-1 text-sm text-muted-foreground">到账确认不会记录单独日期。</p>
        </div>
        {monthSummary.isLoading ? <p role="status">正在加载开票记录…</p> : monthSummary.error ? <p role="alert">开票记录暂时无法显示。</p> : monthSummary.data && <>
          {monthSummary.data.records.length ? <div>
            <div aria-hidden="true" className={`mb-2 hidden gap-3 px-3 text-sm font-medium text-muted-foreground md:grid ${recordGridColumns}`}>
              <span>公司名称</span><span className="text-right">金额</span><span>状态</span><span className="text-right">操作</span>
            </div>
            <ul aria-label={`${month}开票记录`} className="grid gap-2">
            {monthSummary.data.records.map((record) => {
              const transitionKind: RecordTransitionKind = record.status === "pending" ? "confirm" : "revoke";
              const actionsDisabled = transitionRecordMutation.isPending || editRecordMutation.isPending || deleteRecordMutation.isPending;
              return <li className={`grid min-w-0 grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-3 gap-y-2 rounded-lg border p-3 ${recordGridColumns}`} key={record.id}>
              <div className="min-w-0"><span className="block truncate font-medium" title={record.company_name}>{record.company_name}</span></div>
              <div className="text-right"><span className="font-medium tabular-nums">{euro(record.amount)}</span></div>
              <div><span className={`inline-flex rounded-full px-2 py-0.5 text-sm font-medium ring-1 ring-inset ${record.status === "pending" ? "bg-amber-50 text-amber-800 ring-amber-200" : "bg-emerald-50 text-emerald-800 ring-emerald-200"}`}>{record.status === "pending" ? "待到账" : "已确认"}</span></div>
              <div className="col-span-3 flex justify-end gap-2 md:col-span-1">
                {record.status === "pending" && <Button aria-label={`确认${record.company_name}开票记录到账`} disabled={actionsDisabled} onClick={() => openRecordTransition(record, transitionKind)} type="button">确认到账</Button>}
                <RecordActionsMenu
                  disabled={actionsDisabled}
                  onDelete={() => {
                    setRecordError("");
                    setRecordMessage("");
                    deleteRecordMutation.reset();
                    setRecordToDelete(record);
                  }}
                  onEdit={() => openRecordEditor(record)}
                  onRevoke={() => openRecordTransition(record, transitionKind)}
                  record={record}
                />
              </div>
            </li>;
            })}
            </ul>
          </div> : <p>本月暂无开票记录。</p>}
          {recordMessage && <p role="status">{recordMessage}</p>}
        </>}
      </section>
      <Dialog open={editingRecord !== null} onOpenChange={(open) => {
        if (!open && !editRecordMutation.isPending) setEditingRecord(null);
      }}>
        <DialogContent aria-label="修改开票记录">
          <DialogHeader>
            <DialogTitle>修改开票记录</DialogTitle>
            <DialogDescription>开票月份保持为 {editingRecord?.opening_month}；只能修改待到账记录。</DialogDescription>
          </DialogHeader>
          <label className="grid gap-1 text-sm font-medium">
            编辑结算公司
            <select aria-label="编辑结算公司" className="h-9 rounded-md border border-input bg-transparent px-3 text-sm" disabled={editRecordMutation.isPending} onChange={(event) => setEditCompanyId(event.target.value)} value={editCompanyId}>
              {(active.data ?? []).map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium">
            编辑金额（整数欧元）
            <Input aria-label="编辑金额（整数欧元）" disabled={editRecordMutation.isPending} inputMode="numeric" max={MAX_SETTLEMENT_AMOUNT} min="1" onChange={(event) => setEditAmount(event.target.value)} pattern="[0-9]+" required step="1" type="number" value={editAmount} />
          </label>
          {editingRecord && recordError && <div role="alert">{recordError}</div>}
          <DialogFooter>
            <DialogClose asChild><Button disabled={editRecordMutation.isPending} type="button" variant="outline">取消修改</Button></DialogClose>
            {editRecordMutation.isError && <Button disabled={editRecordMutation.isPending} onClick={submitRecordEdit} type="button" variant="outline">重试修改</Button>}
            <Button disabled={editRecordMutation.isPending || !editCompanyId || !validAmount(editAmount)} onClick={submitRecordEdit} type="button">保存开票记录修改</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <AlertDialog open={recordToDelete !== null} onOpenChange={(open) => {
        if (!open && !deleteRecordMutation.isPending) setRecordToDelete(null);
      }}>
        <AlertDialogContent aria-label="永久删除开票记录？">
          <AlertDialogHeader>
            <AlertDialogTitle>永久删除开票记录？</AlertDialogTitle>
            <AlertDialogDescription>将永久删除 {recordToDelete?.company_name} 的待到账开票记录，此操作无法撤销。</AlertDialogDescription>
          </AlertDialogHeader>
          {recordToDelete && recordError && <div role="alert">{recordError}</div>}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteRecordMutation.isPending}>取消删除</AlertDialogCancel>
            <Button aria-label="确认永久删除开票记录" disabled={deleteRecordMutation.isPending} onClick={submitRecordDelete} type="button" variant="destructive">确认永久删除</Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={recordTransition !== null} onOpenChange={(open) => {
        if (!open && !transitionRecordMutation.isPending) {
          setRecordTransition(null);
          setRecordError("");
          transitionRecordMutation.reset();
        }
      }}>
        <AlertDialogContent aria-label={recordTransition ? recordTransitionConfig[recordTransition.kind].dialogTitle : undefined}>
          <AlertDialogHeader>
            <AlertDialogTitle>{recordTransition && recordTransitionConfig[recordTransition.kind].dialogTitle}</AlertDialogTitle>
            <AlertDialogDescription>
              {recordTransition && recordTransitionConfig[recordTransition.kind].description(recordTransition.record)}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {recordTransition && recordError && <div role="alert">{recordError}</div>}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={transitionRecordMutation.isPending}>取消</AlertDialogCancel>
            <Button disabled={transitionRecordMutation.isPending} onClick={submitRecordTransition} type="button" variant={recordTransition ? recordTransitionConfig[recordTransition.kind].variant : "default"}>
              {recordTransition && recordTransitionConfig[recordTransition.kind].actionLabel}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <section className="grid min-w-0 gap-3" aria-labelledby="company-management-title">
        <h2 id="company-management-title">
          <button
            aria-expanded={companyManagementOpen}
            className="group flex w-full min-w-0 items-center gap-3 py-2 text-left text-xl font-semibold text-foreground transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            onClick={() => setCompanyManagementStoreId((storeId) => storeId === selected.id ? null : selected.id)}
            type="button"
          >
            <span className="min-w-0">结算公司管理</span>
            {companyManagementOpen && <span className="sr-only">
              ，使用中 {active.data?.length ?? 0}，已归档 {archived.data?.length ?? 0}
            </span>}
            <span aria-hidden="true" className="h-px min-w-0 flex-1 bg-border" />
            <ChevronDown aria-hidden="true" className={`size-5 shrink-0 text-muted-foreground transition-transform duration-200 ${companyManagementOpen ? "rotate-180" : ""}`} />
          </button>
        </h2>
        {companyManagementOpen && <Tabs className="min-w-0" onValueChange={(value) => setCompanyTab(value as "active" | "archived")} value={companyTab}>
          <TabsList aria-label="结算公司状态" className="grid h-auto w-full grid-cols-2">
            <TabsTrigger className="min-w-0 px-2" value="active">使用中（{active.data?.length ?? 0}）</TabsTrigger>
            <TabsTrigger className="min-w-0 px-2" value="archived">已归档（{archived.data?.length ?? 0}）</TabsTrigger>
          </TabsList>
          <TabsContent className="min-w-0" value="active">
            <form className="mb-2 flex min-w-0 flex-wrap gap-2" onSubmit={create}>
              <label className="min-w-0 flex-1">
                <span className="sr-only">新结算公司名称</span>
                <Input maxLength={120} placeholder="输入结算公司名称" value={name} onChange={(event) => setName(event.target.value)} />
              </label>
              <Button disabled={companyMutation.isPending} type="submit">新增结算公司</Button>
            </form>
            <div aria-label={`使用中结算公司（${active.data?.length ?? 0}）`} className="max-h-64 min-w-0 overflow-y-auto overscroll-contain pr-1" role="region" tabIndex={0}>
              {active.isLoading ? <p role="status">加载使用中的公司…</p> : active.error ? <div role="alert"><p>{friendlyApiError(active.error, "使用中的公司加载失败")}</p><Button onClick={() => void active.refetch()} type="button" variant="outline">重试使用中的公司</Button></div> : <CompanyList key={`${selected.id}:active`} companies={active.data ?? []} archived={false} busy={companyMutation.isPending} onRename={(company, next) => runCompanyAction(selected.id, `/settlements/${selected.id}/companies/${company.id}`, "PATCH", { name: next })} onLifecycle={(company) => runCompanyAction(selected.id, `/settlements/${selected.id}/companies/${company.id}/archive`, "POST")} onDelete={(company) => runCompanyAction(selected.id, `/settlements/${selected.id}/companies/${company.id}`, "DELETE")} />}
            </div>
          </TabsContent>
          <TabsContent className="min-w-0" value="archived">
            <div aria-label={`已归档结算公司（${archived.data?.length ?? 0}）`} className="max-h-64 min-w-0 overflow-y-auto overscroll-contain pr-1" role="region" tabIndex={0}>
              {archived.isLoading ? <p role="status">加载已归档公司…</p> : archived.error ? <div role="alert"><p>{friendlyApiError(archived.error, "已归档公司加载失败")}</p><Button onClick={() => void archived.refetch()} type="button" variant="outline">重试已归档公司</Button></div> : <CompanyList key={`${selected.id}:archived`} companies={archived.data ?? []} archived busy={companyMutation.isPending} onRename={(company, next) => runCompanyAction(selected.id, `/settlements/${selected.id}/companies/${company.id}`, "PATCH", { name: next })} onLifecycle={(company) => runCompanyAction(selected.id, `/settlements/${selected.id}/companies/${company.id}/restore`, "POST")} onDelete={(company) => runCompanyAction(selected.id, `/settlements/${selected.id}/companies/${company.id}`, "DELETE")} />}
            </div>
          </TabsContent>
        </Tabs>}
      </section>
      {message && <div role="alert">{message}{failedAction && <Button className="ml-2" onClick={failedAction} type="button" variant="outline">重试操作</Button>}</div>}
    </>}
  </section>;
}
