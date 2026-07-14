import { createBrowserRouter, createMemoryRouter, Navigate, Outlet, type RouteObject } from "react-router-dom";

import { AuthProvider, useAuth } from "@/auth/AuthProvider";
import { AppShell } from "@/layouts/AppShell";
import { AdminPage } from "@/pages/AdminPage";
import { LoginPage } from "@/pages/LoginPage";
import { StoreProvider } from "@/stores/StoreProvider";

function AuthLoading() {
  return <main className="flex min-h-screen items-center justify-center" role="status">正在加载…</main>;
}

function ProtectedShell() {
  const { user, isLoading, error } = useAuth();
  if (isLoading) return <AuthLoading />;
  if (error) return <main role="alert">{error.message}</main>;
  if (!user) return <Navigate to="/login" replace />;
  return <StoreProvider><AppShell /></StoreProvider>;
}

function AdminRoute() {
  const { user } = useAuth();
  return user?.role === "admin" ? <AdminPage /> : <Navigate to="/" replace />;
}

function Placeholder({ title }: { title: string }) {
  return <section><h1 className="text-2xl font-semibold">{title}</h1><p className="text-muted-foreground">此页面将在后续任务中实现。</p></section>;
}

const routes: RouteObject[] = [{
  element: <AuthProvider><Outlet /></AuthProvider>,
  children: [
    { path: "/login", element: <LoginPage /> },
    { element: <ProtectedShell />, children: [
      { index: true, element: <Placeholder title="仪表盘" /> },
      { path: "ledger", element: <Placeholder title="每日台账" /> },
      { path: "database", element: <Placeholder title="数据库" /> },
      { path: "charts", element: <Placeholder title="图表" /> },
      { path: "workers", element: <Placeholder title="员工管理（Phase 2）" /> },
      { path: "admin", element: <AdminRoute /> },
    ] },
  ],
}];

export function createAppRouter(initialEntries?: string[]) {
  return initialEntries ? createMemoryRouter(routes, { initialEntries }) : createBrowserRouter(routes);
}
