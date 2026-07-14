import { useQuery } from "@tanstack/react-query";
import { createContext, type PropsWithChildren, useContext, useEffect, useMemo, useState } from "react";

import { api } from "@/api/client";
import type { AccessibleStore } from "@/api/types";

export const accessibleStoresKey = ["stores", "accessible"] as const;

interface StoreContextValue {
  stores: AccessibleStore[];
  selected: AccessibleStore | null;
  select(id: number): void;
  isLoading: boolean;
}

const StoreContext = createContext<StoreContextValue | null>(null);

export function StoreProvider({ children }: PropsWithChildren) {
  const { data: stores = [], isLoading } = useQuery({
    queryKey: accessibleStoresKey,
    queryFn: () => api<AccessibleStore[]>("/stores/accessible"),
  });
  const [selectedId, setSelectedId] = useState<number | null>(null);

  useEffect(() => {
    if (stores.length === 1 && selectedId === null) setSelectedId(stores[0].id);
    else if (selectedId !== null && !stores.some((store) => store.id === selectedId)) setSelectedId(null);
  }, [selectedId, stores]);

  const value = useMemo(
    () => ({
      stores,
      selected: stores.find((store) => store.id === selectedId) ?? null,
      select: setSelectedId,
      isLoading,
    }),
    [isLoading, selectedId, stores],
  );
  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore() {
  const value = useContext(StoreContext);
  if (!value) throw new Error("useStore must be used within StoreProvider");
  return value;
}
