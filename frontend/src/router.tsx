import { createBrowserRouter, createMemoryRouter, Navigate, Outlet, useLocation, type RouteObject } from "react-router-dom";

import { AuthProvider, useAuth } from "@/auth/AuthProvider";
import { AppShell } from "@/layouts/AppShell";
import { AdminPage } from "@/pages/AdminPage";
import { LoginPage } from "@/pages/LoginPage";
import { HomePage } from "@/pages/HomePage";
import { LedgerPage } from "@/pages/LedgerPage";
import { MorePage } from "@/pages/MorePage";
import { BusinessRecordsPage } from "@/pages/BusinessRecordsPage";
import { AccountPasswordPage } from "@/pages/AccountPasswordPage";
import { StoreProvider } from "@/stores/StoreProvider";

function AuthLoading() {
  return <main className="flex min-h-screen items-center justify-center" role="status">正在加载…</main>;
}

function ProtectedShell() {
  const { user, isLoading, error } = useAuth();
  if (isLoading) return <AuthLoading />;
  if (error) return <main role="alert">登录状态加载失败，请重试</main>;
  if (!user) return <Navigate to="/login" replace />;
  return <StoreProvider userId={user.id}><AppShell /></StoreProvider>;
}

function AdminRoute() {
  const { user } = useAuth();
  return user?.role === "admin" ? <AdminPage /> : <Navigate to="/" replace />;
}

function MoreRoute() {
  const location = useLocation();
  const status = (location.state as { status?: unknown } | null)?.status;
  return <>{status === "密码已更新" && <p className="mb-4 text-sm text-primary" role="status">密码已更新</p>}<MorePage /></>;
}

function Placeholder({ title }: { title: string }) {
  return <section><h1 className="text-2xl font-semibold">{title}</h1><p className="text-muted-foreground">此页面将在后续任务中实现。</p></section>;
}

const routes: RouteObject[] = [{
  element: <AuthProvider><Outlet /></AuthProvider>,
  children: [
    { path: "/login", element: <LoginPage /> },
    { element: <ProtectedShell />, children: [
      { index: true, element: <HomePage /> },
      { path: "ledger", element: <LedgerPage /> },
      { path: "database", element: <BusinessRecordsPage /> },
      { path: "more", element: <MoreRoute /> },
      { path: "account/password", element: <AccountPasswordPage /> },
      { path: "workers", element: <Placeholder title="员工管理（Phase 2）" /> },
      { path: "admin", element: <AdminRoute /> },
    ] },
  ],
}];

export function createAppRouter(initialEntries?: string[]) {
  return initialEntries ? createMemoryRouter(routes, { initialEntries }) : createBrowserRouter(routes);
}
