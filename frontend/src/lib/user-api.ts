import type { QueryClient } from "@tanstack/react-query";
import type { AccessibleStore } from "@/api/types";

export const categoryCatalogKey = (storeId: number, date: string) => ["categoryCatalog", storeId, date] as const;
export const ledgerRecordKey = (storeId: number, date: string) => ["ledger", "record", storeId, date] as const;
export const recentKey = (storeId: number) => ["ledger", "recent", storeId, 7] as const;
export const dashboardKey = (storeId: number) => ["dashboard", storeId] as const;
export const chartsKey = (storeId: number, query: string) => ["charts", storeId, query] as const;
export const databaseKey = (storeId: number, query: string) => ["database", "records", storeId, query] as const;

export function storeLocalToday(store: AccessibleStore, now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: store.timezone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

export async function invalidateUserData(client: QueryClient, storeId: number) {
  await client.invalidateQueries({ predicate: ({ queryKey }) => {
    const family = queryKey[0];
    return ["ledger", "database", "charts", "dashboard", "categoryCatalog"].includes(String(family)) && queryKey.includes(storeId);
  } });
}

export function money(value: string | number) { return `€${Number(value).toFixed(2)}`; }
export function amountToCents(value: string): bigint {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d*(\.\d{0,2})?$/.test(normalized)) return 0n;
  const [whole = "0", fraction = ""] = normalized.split(".");
  return BigInt(whole || "0") * 100n + BigInt((fraction + "00").slice(0, 2));
}
export function centsToMoney(value: bigint) { return `€${value / 100n}.${(value % 100n).toString().padStart(2, "0")}`; }
