import type { UserRole } from "@/api/types";

export interface NavigationModule {
  to: string;
  label: string;
  end?: boolean;
}

export const mobileModules = [
  { to: "/", label: "首页", end: true },
  { to: "/ledger", label: "记账" },
  { to: "/database", label: "记录" },
  { to: "/more", label: "更多" },
] as const;

const desktopModules = [
  { to: "/", label: "首页", end: true },
  { to: "/ledger", label: "每日记账" },
  { to: "/database", label: "营业记录" },
  { to: "/settlements", label: "公司结算", capability: "company_settlement" },
] as const;

const adminModule = { to: "/admin", label: "管理中心" } as const;

export function navigationFor(role: UserRole, surface: "desktop" | "mobile", companySettlementEnabled = false): readonly NavigationModule[] {
  if (surface === "mobile") return mobileModules;
  const availableModules = desktopModules.filter((module) => !("capability" in module) || companySettlementEnabled);
  return role === "admin" ? [...availableModules, adminModule] : availableModules;
}
