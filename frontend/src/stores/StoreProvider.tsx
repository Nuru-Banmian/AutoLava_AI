import { useQuery } from "@tanstack/react-query";
import { createContext, type PropsWithChildren, useContext, useEffect, useMemo, useState } from "react";

import { api } from "@/api/client";
import type { AccessibleStore } from "@/api/types";

export const accessibleStoresKey = ["stores", "accessible"] as const;
export const STORE_SELECTION_KEY = "autolava:selected-store";

interface StoreContextValue {
  stores: AccessibleStore[];
  selected: AccessibleStore | null;
  select(id: number): void;
  isLoading: boolean;
  error: Error | null;
  refetch(): Promise<unknown>;
}

const StoreContext = createContext<StoreContextValue | null>(null);

export function StoreProvider({ children }: PropsWithChildren) {
  const { data: stores = [], isLoading, isSuccess, error, refetch } = useQuery({
    queryKey: accessibleStoresKey,
    queryFn: () => api<AccessibleStore[]>("/stores/accessible"),
  });
  const [selectedId, setSelectedId] = useState<number | null>(
    () => Number(localStorage.getItem(STORE_SELECTION_KEY)) || null,
  );

  useEffect(() => {
    if (!isSuccess) return;
    if (selectedId !== null && stores.some((store) => store.id === selectedId)) {
      localStorage.setItem(STORE_SELECTION_KEY, String(selectedId));
      return;
    }

    const fallback = stores[0]?.id ?? null;
    setSelectedId(fallback);
    if (fallback === null) localStorage.removeItem(STORE_SELECTION_KEY);
    else localStorage.setItem(STORE_SELECTION_KEY, String(fallback));
  }, [isSuccess, selectedId, stores]);

  const value = useMemo(
    () => ({
      stores,
      selected: stores.find((store) => store.id === selectedId) ?? null,
      select: setSelectedId,
      isLoading,
      error,
      refetch,
    }),
    [error, isLoading, refetch, selectedId, stores],
  );
  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore() {
  const value = useContext(StoreContext);
  if (!value) throw new Error("useStore must be used within StoreProvider");
  return value;
}
