import { useQuery } from "@tanstack/react-query";
import { createContext, type PropsWithChildren, useContext, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/api/client";
import type { AccessibleStore } from "@/api/types";
import { UnsavedChangesProvider, useUnsavedChanges } from "@/navigation/UnsavedChanges";

export const accessibleStoresKey = ["stores", "accessible"] as const;
export const accessibleStoresKeyFor = (userId: number | undefined) => [...accessibleStoresKey, userId] as const;
export const STORE_SELECTION_KEY = "autolava:selected-store";

interface StoredSelection {
  userId: number;
  storeId: number;
}

function readStoredSelection(userId: number | undefined): number | null {
  if (userId === undefined) return null;
  try {
    const value = JSON.parse(localStorage.getItem(STORE_SELECTION_KEY) ?? "null") as Partial<StoredSelection> | null;
    return value?.userId === userId && Number.isInteger(value.storeId) ? value.storeId ?? null : null;
  } catch {
    return null;
  }
}

function writeStoredSelection(userId: number, storeId: number) {
  localStorage.setItem(STORE_SELECTION_KEY, JSON.stringify({ userId, storeId } satisfies StoredSelection));
}

interface StoreContextValue {
  stores: AccessibleStore[];
  selected: AccessibleStore | null;
  select(id: number): void;
  isLoading: boolean;
  error: Error | null;
  refetch(): Promise<unknown>;
}

const StoreContext = createContext<StoreContextValue | null>(null);

interface StoreProviderProps extends PropsWithChildren {
  userId?: number;
}

function StoreStateProvider({ children, userId }: StoreProviderProps) {
  const { requestTransition, resetUnsavedChanges } = useUnsavedChanges();
  const { data: stores = [], isLoading, isSuccess, error, refetch } = useQuery({
    queryKey: accessibleStoresKeyFor(userId),
    queryFn: () => api<AccessibleStore[]>("/stores/accessible"),
  });
  const [selection, setSelection] = useState<{ userId: number | undefined; storeId: number | null; snapshot: AccessibleStore | null }>(() => ({ userId, storeId: readStoredSelection(userId), snapshot: null }));
  const reconciliationRef = useRef<string | null>(null);
  const sameUser = selection.userId === userId;
  const selectedId = sameUser ? selection.storeId : null;
  const liveSelected = sameUser ? stores.find((store) => store.id === selectedId) ?? null : null;
  const selected = liveSelected ?? (sameUser ? selection.snapshot : null);

  useEffect(() => {
    if (!sameUser) {
      reconciliationRef.current = null;
      resetUnsavedChanges();
      setSelection({ userId, storeId: readStoredSelection(userId), snapshot: null });
      return;
    }
    if (!isSuccess) return;
    if (liveSelected) {
      reconciliationRef.current = null;
      if (userId !== undefined) writeStoredSelection(userId, liveSelected.id);
      if (selection.snapshot !== liveSelected) {
        setSelection({ userId, storeId: selectedId, snapshot: liveSelected });
      }
      return;
    }

    const fallback = stores[0] ?? null;
    const reconciliationKey = `${userId ?? "none"}:${selectedId ?? "none"}:${fallback?.id ?? "none"}:${stores.map((store) => store.id).join(",")}`;
    if (reconciliationRef.current === reconciliationKey) return;
    reconciliationRef.current = reconciliationKey;
    requestTransition(() => {
      setSelection({ userId, storeId: fallback?.id ?? null, snapshot: fallback });
      if (userId === undefined) return;
      if (fallback === null) localStorage.removeItem(STORE_SELECTION_KEY);
      else writeStoredSelection(userId, fallback.id);
    });
  }, [isSuccess, liveSelected, requestTransition, resetUnsavedChanges, sameUser, selectedId, selection.snapshot, stores, userId]);

  const value = useMemo(
    () => ({
      stores,
      selected,
      select: (id: number) => requestTransition(() => setSelection({ userId, storeId: id, snapshot: stores.find((store) => store.id === id) ?? null })),
      isLoading,
      error,
      refetch,
    }),
    [error, isLoading, refetch, requestTransition, selected, stores, userId],
  );
  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function StoreProvider(props: StoreProviderProps) {
  return <UnsavedChangesProvider><StoreStateProvider {...props} /></UnsavedChangesProvider>;
}

export function useStore() {
  const value = useContext(StoreContext);
  if (!value) throw new Error("useStore must be used within StoreProvider");
  return value;
}
