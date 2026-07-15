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
  { to: "/database", label: "历史记录" },
  { to: "/charts", label: "经营分析" },
] as const;

const adminModule = { to: "/admin", label: "管理中心" } as const;

export function navigationFor(role: UserRole, surface: "desktop" | "mobile"): readonly NavigationModule[] {
  if (surface === "mobile") return mobileModules;
  return role === "admin" ? [...desktopModules, adminModule] : desktopModules;
}
