import { Link } from "react-router-dom";
import { Building2, ChevronRight, KeyRound, Settings, Activity, UserRound, MessageSquare } from "lucide-react";

import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { useStore } from "@/stores/StoreProvider";

const moreLinkClass = "flex min-h-14 min-w-0 items-center gap-3 rounded-xl border bg-card px-4 py-3 text-sm font-semibold shadow-sm transition-colors hover:bg-accent";

export function MorePage() {
  const { user, logout, isLoggingOut, logoutError } = useAuth();
  const { selected } = useStore();

  return <section className="grid min-w-0 max-w-3xl gap-5">
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">更多</h1>
      <p className="mt-1 text-sm text-muted-foreground">账号与门店功能</p>
    </div>
    <div className="flex min-w-0 items-center gap-3 rounded-xl border bg-card p-4">
      <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-accent text-primary"><UserRound aria-hidden="true" className="size-5" /></div>
      <div className="min-w-0"><p className="font-semibold">{user?.username}</p><p className="text-xs text-muted-foreground">{user?.is_owner ? "最终管理员" : user?.role === "admin" ? "管理员" : "门店用户"}</p></div>
    </div>
    <nav aria-label="更多功能" className="grid gap-2 sm:grid-cols-2">
      {user?.role === "admin" && <Link className={moreLinkClass} to="/ai"><MessageSquare aria-hidden="true" className="size-5 shrink-0 text-primary" /><span className="min-w-0 flex-1">AI 对话</span><ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" /></Link>}
      {selected?.company_settlement_enabled && <Link className={moreLinkClass} to="/settlements"><Building2 aria-hidden="true" className="size-5 shrink-0 text-primary" /><span className="min-w-0 flex-1">公司结算</span><ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" /></Link>}
      <Link className={moreLinkClass} to="/account/password"><KeyRound aria-hidden="true" className="size-5 shrink-0 text-primary" /><span className="min-w-0 flex-1">修改密码</span><ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" /></Link>
      {user?.role === "admin" && <Link className={moreLinkClass} to="/admin"><Settings aria-hidden="true" className="size-5 shrink-0 text-primary" /><span className="min-w-0 flex-1">管理中心</span><ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" /></Link>}
      {user?.role === "admin" && <Link className={moreLinkClass} to="/admin?tab=status"><Activity aria-hidden="true" className="size-5 shrink-0 text-primary" /><span className="min-w-0 flex-1">系统状态</span><ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" /></Link>}
    </nav>
    <Button className="w-full text-destructive sm:w-fit" variant="outline" disabled={isLoggingOut} onClick={() => { void logout().catch(() => undefined); }}>退出登录</Button>
    {logoutError && <p role="alert" className="text-sm text-destructive">退出失败，请重试</p>}
  </section>;
}
