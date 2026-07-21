import { BookOpen, Building2, Database, Home, LogOut, Menu, Settings } from "lucide-react";
import type { ComponentType, SVGProps } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "@/auth/AuthProvider";
import { StorePicker } from "@/components/StorePicker";
import { Button } from "@/components/ui/button";
import { navigationFor } from "@/navigation/modules";
import { useStore } from "@/stores/StoreProvider";
import { UnsavedRouteGuard } from "@/navigation/UnsavedChanges";

type Icon = ComponentType<SVGProps<SVGSVGElement>>;

const icons: Record<string, Icon> = {
  "/": Home,
  "/ledger": BookOpen,
  "/settlements": Building2,
  "/database": Database,
  "/admin": Settings,
  "/more": Menu,
};

function Navigation({ surface }: { surface: "desktop" | "mobile" }) {
  const { user } = useAuth();
  const { selected } = useStore();
  if (!user) return null;

  return <>
    {navigationFor(user.role, surface, selected?.company_settlement_enabled).map(({ to, label, end }) => {
      const Icon = icons[to];
      return <NavLink
        key={to}
        to={to}
        end={end}
        className={({ isActive }) => surface === "desktop"
          ? `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium ${isActive ? "bg-white/15 text-primary-foreground" : "text-primary-foreground/80 hover:bg-white/10 hover:text-primary-foreground"}`
          : `flex min-w-0 flex-col items-center gap-1 rounded-md px-1 py-1 text-xs ${isActive ? "text-primary" : "text-muted-foreground"}`}
      >
        <Icon aria-hidden="true" className="size-5 shrink-0" />
        <span className="truncate">{label}</span>
      </NavLink>;
    })}
  </>;
}

export function AppShell() {
  const { user, logout, isLoggingOut, logoutError } = useAuth();
  const { error: storeError, refetch: refetchStores } = useStore();
  const { pathname } = useLocation();
  const isAdminRoute = pathname === "/admin" || pathname.startsWith("/admin/");

  return (
    <div className="min-h-screen bg-muted/20 md:pl-64">
      <UnsavedRouteGuard />
      <header className="border-b bg-background md:fixed md:left-0 md:top-0 md:z-40 md:w-64 md:border-0 md:bg-transparent md:text-primary-foreground">
        <div className="flex items-center gap-3 px-4 py-3"><strong>AutoLava AI</strong>{!isAdminRoute && <div data-testid="mobile-store-picker" className="ml-auto w-40 max-w-[55vw] md:hidden"><StorePicker showLabel={false} /></div>}</div>
      </header>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col bg-primary p-4 text-primary-foreground md:flex">
        <div className="mt-16 grid gap-3">
          {!isAdminRoute && <div data-testid="desktop-store-picker" className="min-w-0 max-w-full [&_select]:bg-background [&_select]:text-foreground"><StorePicker /></div>}
          <nav aria-label="主导航" className="grid gap-1"><Navigation surface="desktop" /></nav>
        </div>
        <div className="mt-auto grid gap-3 border-t border-white/20 pt-4 [&_select]:bg-background [&_select]:text-foreground">
          <div className="flex items-center justify-between gap-2">
            <span className="min-w-0 truncate text-sm">{user?.username}</span>
            <Button aria-label="退出登录" disabled={isLoggingOut} onClick={() => { void logout().catch(() => undefined); }} size="icon" variant="secondary"><LogOut /></Button>
          </div>
        </div>
      </aside>
      <main className="mx-auto max-w-7xl p-4 pb-24 md:p-6 md:pb-6">
        {logoutError && <p className="mb-4 text-sm text-destructive" role="alert">退出失败，请重试</p>}
        {!isAdminRoute && storeError && <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-destructive" role="alert"><span>门店加载失败，请重试</span><Button aria-label="重试门店" onClick={() => { void refetchStores(); }} size="sm" variant="outline">重试</Button></div>}
        <Outlet />
      </main>
      <nav aria-label="移动导航" className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t bg-background px-1 py-2 md:hidden"><Navigation surface="mobile" /></nav>
    </div>
  );
}
