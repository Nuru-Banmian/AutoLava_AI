import { BarChart3, BookOpen, Database, Home, LogOut, Settings, Users } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { useStore } from "@/stores/StoreProvider";

const links = [
  { to: "/", label: "仪表盘", icon: Home },
  { to: "/ledger", label: "每日台账", icon: BookOpen },
  { to: "/database", label: "数据库", icon: Database },
  { to: "/charts", label: "图表", icon: BarChart3 },
];

function NavItems({ mobile = false }: { mobile?: boolean }) {
  const { user } = useAuth();
  return <>
    {links.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === "/"} className="flex items-center gap-1 rounded-md px-3 py-2 text-sm"><Icon />{label}</NavLink>)}
    <span aria-disabled="true" title="Phase 2 提供" className="flex cursor-not-allowed items-center gap-1 px-3 py-2 text-sm opacity-50"><Users />员工管理<span className={mobile ? "sr-only" : "text-xs"}>（Phase 2）</span></span>
    {user?.role === "admin" && <NavLink to="/admin" className="flex items-center gap-1 rounded-md px-3 py-2 text-sm"><Settings />管理</NavLink>}
  </>;
}

export function AppShell() {
  const { user, logout, isLoggingOut } = useAuth();
  const { stores, selected, select, isLoading } = useStore();
  return (
    <div className="min-h-screen bg-muted/20">
      <header className="border-b bg-background">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
          <strong>AutoLava AI</strong>
          <nav aria-label="主导航" className="hidden flex-1 items-center gap-1 md:flex"><NavItems /></nav>
          <label className="ml-auto flex items-center gap-2 text-sm">门店
            <select aria-label="门店" className="rounded-md border bg-background p-2" disabled={isLoading || stores.length === 0} value={selected?.id ?? ""} onChange={(event) => select(Number(event.target.value))}>
              <option value="">请选择门店</option>{stores.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
            </select>
          </label>
          <span className="hidden text-sm lg:inline">{user?.username}</span>
          <Button aria-label="退出登录" disabled={isLoggingOut} onClick={() => void logout()} size="icon" variant="ghost"><LogOut /></Button>
        </div>
      </header>
      <main className="mx-auto max-w-7xl p-4 pb-24 md:pb-6"><Outlet /></main>
      <nav aria-label="移动导航" className="fixed inset-x-0 bottom-0 z-40 flex justify-around border-t bg-background p-2 md:hidden"><NavItems mobile /></nav>
    </div>
  );
}
