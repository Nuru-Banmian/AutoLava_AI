import { Link } from "react-router-dom";

import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { useStore } from "@/stores/StoreProvider";

const moreLinkClass = "rounded-lg border bg-background px-4 py-3 text-sm font-medium hover:bg-accent";

export function MorePage() {
  const { user, logout, isLoggingOut, logoutError } = useAuth();
  const { selected } = useStore();

  return <section className="grid gap-4">
    <h1 className="text-2xl font-semibold">更多</h1>
    <nav aria-label="更多功能" className="grid gap-2">
      {selected?.company_settlement_enabled && <Link className={moreLinkClass} to="/settlements">公司结算</Link>}
      <Link className={moreLinkClass} to="/account/password">修改密码</Link>
      {user?.role === "admin" && <Link className={moreLinkClass} to="/admin">管理中心</Link>}
      {user?.role === "admin" && <Link className={moreLinkClass} to="/admin?tab=status">系统状态</Link>}
    </nav>
    <Button disabled={isLoggingOut} onClick={() => { void logout().catch(() => undefined); }}>退出登录</Button>
    {logoutError && <p role="alert" className="text-sm text-destructive">退出失败，请重试</p>}
  </section>;
}
