import type { QueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { AccessibleStore, CategoryDescriptor, DatabaseResponse } from "@/api/types";

export const categoryCatalogKey = (storeId: number, start: string, end = start) => ["categoryCatalog", storeId, start, end] as const;
export const incomeConfigKey = (storeId: number) => ["income-config", storeId, "current"] as const;
export const ledgerRecordKey = (storeId: number, date: string) => ["ledger", "record", storeId, date] as const;
export const recentKey = (storeId: number) => ["ledger", "recent", storeId, 7] as const;
export const dashboardKey = (storeId: number) => ["dashboard", storeId] as const;
export const chartsKey = (storeId: number, query: string) => ["charts", storeId, query] as const;
export const databaseKey = (storeId: number, query: string) => ["database", "records", storeId, query] as const;

export async function loadCategoryCatalog(storeId: number, start: string, end: string, signal?: AbortSignal): Promise<DatabaseResponse> {
  const categories = new Map<number, CategoryDescriptor>();
  let firstPage: DatabaseResponse | null = null;
  let page = 1;
  let total = 0;

  do {
    const query = new URLSearchParams({ start, end, page: String(page), page_size: "200" });
    const response = await api<DatabaseResponse>(`/database/${storeId}/records?${query}`, { signal });
    firstPage ??= response;
    total = Math.max(total, response.total);
    response.categories.forEach((category) => categories.set(category.id, category));
    page += 1;
  } while ((page - 1) * 200 < total);

  return {
    ...firstPage!,
    categories: [...categories.values()].sort((left, right) => left.sort_order - right.sort_order || left.id - right.id),
    total,
  };
}

export function storeLocalToday(store: AccessibleStore, now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: store.timezone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

export async function invalidateUserData(client: QueryClient, storeId: number) {
  await client.invalidateQueries({ predicate: ({ queryKey }) => {
    if (queryKey[0] === "ledger" || queryKey[0] === "database") return queryKey[2] === storeId;
    if (queryKey[0] === "charts" || queryKey[0] === "dashboard" || queryKey[0] === "categoryCatalog") return queryKey[1] === storeId;
    return false;
  } });
}

const amountError = "请输入 0 至 9999999999.99 之间、最多两位小数的金额";
export function canonicalAmount(input: string): { value: string } | { error: string } {
  const normalized = input.trim().replace(",", ".");
  if (!/^\d+(\.\d{0,2})?$/.test(normalized)) return { error: amountError };
  const [whole, fraction = ""] = normalized.split(".");
  const canonical = `${BigInt(whole)}.${(fraction + "00").slice(0, 2)}`;
  if (BigInt(canonical.replace(".", "")) > 999999999999n) return { error: amountError };
  return { value: canonical };
}
export function amountToCents(value: string): bigint | null { const result = canonicalAmount(value); return "value" in result ? BigInt(result.value.replace(".", "")) : null; }
export function centsToMoney(value: bigint) { return `€${value / 100n}.${(value % 100n).toString().padStart(2, "0")}`; }
export function formatMoney(input: string | number) {
  const normalized = String(input).trim(); const match = normalized.match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!match) return `€${normalized}`;
  return `€${match[1]}${match[2]}.${((match[3] ?? "") + "00").slice(0, 2)}`;
}
export const money = formatMoney;
export function chartNumber(input: string): number {
  const value = Number(input); if (!Number.isFinite(value)) return 0;
  return Math.max(-Number.MAX_SAFE_INTEGER, Math.min(Number.MAX_SAFE_INTEGER, value));
}
