import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, friendlyApiError } from "@/api/client";
import type { AdminStore } from "@/api/types";
import { IncomeItemsPanel } from "@/admin/IncomeItemsPanel";
import { StoreDetailsCard } from "@/admin/StoreDetailsCard";
import { Button } from "@/components/ui/button";
import { useUnsavedChanges } from "@/navigation/UnsavedChanges";

const storesKey = ["admin", "stores"] as const;
type StoreSelection = number | "new" | null;

export function StoreWorkspace() {
  const [selection, setSelection] = useState<StoreSelection>(null);
  const selectionRef = useRef<StoreSelection>(null);
  const initializedSelectionRef = useRef(false);
  const [detailsDirty, setDetailsDirty] = useState(false);
  const [incomeDirty, setIncomeDirty] = useState(false);
  const detailsDirtyRef = useRef(false);
  const incomeDirtyRef = useRef(false);
  const { markDirty, requestTransition } = useUnsavedChanges();
  const stores = useQuery({ queryKey: storesKey, queryFn: () => api<AdminStore[]>("/admin/stores") });
  const list = stores.data ?? [];

  useEffect(() => markDirty(detailsDirty || incomeDirty), [detailsDirty, incomeDirty, markDirty]);
  useEffect(() => () => markDirty(false), [markDirty]);

  function commitSelection(next: StoreSelection) {
    selectionRef.current = next;
    setSelection(next);
  }

  useEffect(() => {
    if (!stores.isSuccess || initializedSelectionRef.current) return;
    initializedSelectionRef.current = true;
    if (selectionRef.current === null && list[0]) commitSelection(list[0].id);
  }, [list, stores.isSuccess]);

  const updateDetailsDirty = useCallback((dirty: boolean) => {
    detailsDirtyRef.current = dirty;
    setDetailsDirty(dirty);
  }, []);

  const updateIncomeDirty = useCallback((dirty: boolean) => {
    incomeDirtyRef.current = dirty;
    setIncomeDirty(dirty);
  }, []);

  function select(next: StoreSelection) {
    if (selectionRef.current === next) return;
    requestTransition(() => {
      updateDetailsDirty(false);
      updateIncomeDirty(false);
      commitSelection(next);
    });
  }

  function created(store: AdminStore) {
    if (selectionRef.current !== "new") return;
    updateDetailsDirty(false);
    commitSelection(store.id);
  }

  async function finishDeleted(storeId: number) {
    if (selectionRef.current !== storeId) return;
    const result = await stores.refetch();
    if (selectionRef.current !== storeId) return;
    updateDetailsDirty(false);
    updateIncomeDirty(false);
    commitSelection(result.data?.find((store) => store.id !== storeId)?.id ?? null);
  }

  function deleted(storeId: number) {
    if (selectionRef.current !== storeId) return;
    void finishDeleted(storeId);
  }

  const selectedStore = typeof selection === "number"
    ? list.find((store) => store.id === selection) ?? null
    : null;

  let cards: React.ReactNode = null;
  if (selection === "new") {
    cards = <StoreDetailsCard
      key={selection}
      mode="create"
      onDeleted={() => undefined}
      onDeleteFailed={() => undefined}
      onDeleteRequested={() => undefined}
      onDirtyChange={updateDetailsDirty}
      onSaved={created}
      store={null}
    />;
  } else if (selectedStore) {
    const capturedStoreId = selectedStore.id;
    cards = <div className="space-y-4">
      <IncomeItemsPanel key={`income-${selection}`} onDirtyChange={updateIncomeDirty} storeId={selectedStore.id} />
      <StoreDetailsCard
        key={`details-${selection}`}
        mode="edit"
        onDeleted={(storeId) => {
          if (selectionRef.current === capturedStoreId) deleted(storeId);
        }}
        onDeleteRequested={(deleteStore) => {
          if (selectionRef.current !== capturedStoreId) return;
          requestTransition(() => {
            if (selectionRef.current === capturedStoreId) deleteStore();
          });
        }}
        onDeleteFailed={() => {
          if (selectionRef.current === capturedStoreId && (detailsDirtyRef.current || incomeDirtyRef.current)) markDirty(true);
        }}
        onDirtyChange={updateDetailsDirty}
        onSaved={() => {
          if (selectionRef.current === capturedStoreId) updateDetailsDirty(false);
        }}
        store={selectedStore}
      />
    </div>;
  }

  return <div className="space-y-4">
    {stores.error && <p role="alert" className="text-sm text-destructive">{friendlyApiError(stores.error, "门店加载失败")}</p>}
    <div className="flex items-center gap-2">
      <select
        aria-label="门店"
        className="h-9 min-w-0 flex-1 rounded-md border bg-background px-2 md:hidden"
        onChange={(event) => {
          if (event.target.value) select(Number(event.target.value));
        }}
        value={typeof selection === "number" ? selection : ""}
      >
        <option hidden value="" />
        {list.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
      </select>
      <Button type="button" onClick={() => select("new")}>新建门店</Button>
    </div>
    <div className="gap-4 md:grid md:grid-cols-[14rem_minmax(0,1fr)]">
      <aside className="hidden md:block">
        <ul className="divide-y rounded-lg border bg-card">
          {list.map((store) => <li key={store.id}>
            <button className="w-full p-3 text-left hover:bg-accent" onClick={() => select(store.id)} type="button">
              <span className="block font-medium">{store.name}</span>
              <span className="text-xs text-muted-foreground">{store.address}</span>
            </button>
          </li>)}
        </ul>
      </aside>
      <main>{cards}</main>
    </div>
  </div>;
}
