import { useQuery } from "@tanstack/react-query";
import { createContext, type PropsWithChildren, useContext, useEffect, useMemo, useState } from "react";

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
  const { requestTransition } = useUnsavedChanges();
  const { data: stores = [], isLoading, isSuccess, error, refetch } = useQuery({
    queryKey: accessibleStoresKeyFor(userId),
    queryFn: () => api<AccessibleStore[]>("/stores/accessible"),
  });
  const [selection, setSelection] = useState(() => ({ userId, storeId: readStoredSelection(userId) }));
  const selectedId = selection.userId === userId ? selection.storeId : readStoredSelection(userId);

  useEffect(() => {
    if (!isSuccess) return;
    if (selectedId !== null && stores.some((store) => store.id === selectedId)) {
      if (userId !== undefined) writeStoredSelection(userId, selectedId);
      if (selection.userId !== userId || selection.storeId !== selectedId) {
        setSelection({ userId, storeId: selectedId });
      }
      return;
    }

    const fallback = stores[0]?.id ?? null;
    if (selection.userId !== userId || selection.storeId !== fallback) {
      setSelection({ userId, storeId: fallback });
    }
    if (userId === undefined) return;
    if (fallback === null) localStorage.removeItem(STORE_SELECTION_KEY);
    else writeStoredSelection(userId, fallback);
  }, [isSuccess, selectedId, selection.storeId, selection.userId, stores, userId]);

  const value = useMemo(
    () => ({
      stores,
      selected: stores.find((store) => store.id === selectedId) ?? null,
      select: (id: number) => requestTransition(() => setSelection({ userId, storeId: id })),
      isLoading,
      error,
      refetch,
    }),
    [error, isLoading, refetch, requestTransition, selectedId, stores, userId],
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
