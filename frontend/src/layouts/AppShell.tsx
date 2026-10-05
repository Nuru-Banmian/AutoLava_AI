import { BookOpen, Building2, Database, Home, LogOut, Menu, MessageSquare, Settings } from "lucide-react";
import type { ComponentType, SVGProps } from "react";
import { Link, matchPath, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "@/auth/AuthProvider";
import { StorePicker } from "@/components/StorePicker";
import { Button } from "@/components/ui/button";
import { navigationFor } from "@/navigation/modules";
import { useStore } from "@/stores/StoreProvider";
import { UnsavedRouteGuard, useUnsavedChanges } from "@/navigation/UnsavedChanges";

type Icon = ComponentType<SVGProps<SVGSVGElement>>;

const icons: Record<string, Icon> = {
  "/": Home,
  "/ledger": BookOpen,
  "/settlements": Building2,
  "/database": Database,
  "/admin": Settings,
  "/ai": MessageSquare,
  "/more": Menu,
};

function Navigation({ surface }: { surface: "desktop" | "mobile" }) {
  const { user } = useAuth();
  const { selected } = useStore();
  const { pathname } = useLocation();
  if (!user) return null;

  return <>
    {navigationFor(user.role, surface, selected?.company_settlement_enabled).map(({ to, label, end }) => {
      const Icon = icons[to];
      const isMorePage = to === "/more" && surface === "mobile" &&
        ["/more", "/settlements", "/account", "/admin", "/ai"].some((path) => Boolean(matchPath({ path, end: false }, pathname)));
      const isActive = isMorePage || Boolean(matchPath({ path: to, end: end ?? false }, pathname));
      return <Link
        key={to}
        to={to}
        aria-current={isActive ? "page" : undefined}
        className={surface === "desktop"
          ? `flex min-h-11 items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white ${isActive ? "bg-white text-primary" : "text-primary-foreground/85 hover:bg-white/10 hover:text-primary-foreground"}`
          : `flex min-h-12 min-w-0 flex-col items-center justify-center gap-1 rounded-lg px-1 py-1.5 text-xs font-semibold ${isActive ? "bg-accent text-primary" : "text-muted-foreground hover:bg-muted"}`}
      >
        <Icon aria-hidden="true" className="size-5 shrink-0" />
        <span className="truncate">{label}</span>
      </Link>;
    })}
  </>;
}

export function AppShell() {
  const { requestTransition } = useUnsavedChanges();
  const { user, logout, isLoggingOut, logoutError } = useAuth();
  const { error: storeError, refetch: refetchStores } = useStore();
  const { pathname } = useLocation();
  const isAdminRoute = pathname === "/admin" || pathname.startsWith("/admin/");

  return (
    <div className="min-h-dvh min-w-0 bg-background md:pl-64">
      <UnsavedRouteGuard />
      <header className="border-b bg-card md:fixed md:left-0 md:top-0 md:z-40 md:w-64 md:border-0 md:bg-transparent md:text-primary-foreground">
        <div className="flex min-w-0 flex-wrap items-center gap-3 px-4 py-3 md:px-6 md:py-5">
          <div className="flex shrink-0 items-center gap-2.5">
            <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary md:bg-white/15 md:text-white md:ring-1 md:ring-white/20"><Building2 className="size-5" strokeWidth={1.8} /></span>
            <strong className="whitespace-nowrap text-lg font-bold leading-tight tracking-[0.04em] text-primary md:text-[22px] md:text-white">门店管理系统</strong>
          </div>
          {!isAdminRoute && <div data-testid="mobile-store-picker" className="ml-auto min-w-0 max-w-full flex-1 basis-36 md:hidden"><StorePicker showLabel={false} /></div>}
        </div>
      </header>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col overflow-y-auto bg-primary p-4 text-primary-foreground md:flex">
        <div className="mt-16 grid gap-3">
          {!isAdminRoute && <div data-testid="desktop-store-picker" className="min-w-0 max-w-full rounded-xl border border-white/15 bg-white/5 p-3"><StorePicker /></div>}
          <nav aria-label="主导航" className="grid gap-1"><Navigation surface="desktop" /></nav>
        </div>
        <div className="mt-auto grid gap-3 border-t border-white/20 pt-4 [&_select]:bg-background [&_select]:text-foreground">
          <div className="flex items-center justify-between gap-2">
            <span className="min-w-0 truncate text-sm">{user?.username}</span>
            <Button aria-label="退出登录" disabled={isLoggingOut} onClick={() => requestTransition(() => { void logout().catch(() => undefined); }, undefined, { preserveDirty: true })} size="icon" variant="secondary"><LogOut /></Button>
          </div>
        </div>
      </aside>
      <main className="mx-auto min-w-0 w-full max-w-7xl p-3 pb-28 sm:p-4 sm:pb-28 md:p-6 md:pb-6">
        {logoutError && <p className="mb-4 text-sm text-destructive" role="alert">退出失败，请重试</p>}
        {!isAdminRoute && storeError && <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-destructive" role="alert"><span>门店加载失败，请重试</span><Button aria-label="重试门店" onClick={() => { void refetchStores(); }} size="sm" variant="outline">重试</Button></div>}
        <Outlet />
      </main>
      <nav aria-label="移动导航" className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 gap-1 border-t bg-card px-2 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] shadow-[0_-2px_12px_rgb(15_23_42_/_4%)] md:hidden"><Navigation surface="mobile" /></nav>
    </div>
  );
}
