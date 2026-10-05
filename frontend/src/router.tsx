import { Component, lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, createMemoryRouter, Navigate, Outlet, useLocation, type RouteObject } from "react-router-dom";

import { AuthProvider, useAuth } from "@/auth/AuthProvider";
import { AppShell } from "@/layouts/AppShell";
import { StoreProvider } from "@/stores/StoreProvider";

const AdminPage = lazy(() => import("@/pages/AdminPage").then((module) => ({ default: module.AdminPage })));
const AgentChatPage = lazy(() => import("@/pages/AgentChatPage").then((module) => ({ default: module.AgentChatPage })));
const LoginPage = lazy(() => import("@/pages/LoginPage").then((module) => ({ default: module.LoginPage })));
const HomePage = lazy(() => import("@/pages/HomePage").then((module) => ({ default: module.HomePage })));
const LedgerPage = lazy(() => import("@/pages/LedgerPage").then((module) => ({ default: module.LedgerPage })));
const MorePage = lazy(() => import("@/pages/MorePage").then((module) => ({ default: module.MorePage })));
const BusinessRecordsPage = lazy(() => import("@/pages/BusinessRecordsPage").then((module) => ({ default: module.BusinessRecordsPage })));
const AccountPasswordPage = lazy(() => import("@/pages/AccountPasswordPage").then((module) => ({ default: module.AccountPasswordPage })));
const CompanySettlementPage = lazy(() => import("@/pages/CompanySettlementPage").then((module) => ({ default: module.CompanySettlementPage })));

class PageLoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() { return { failed: true }; }

  render() {
    if (this.state.failed) return <main role="alert" className="p-6">页面资源加载失败。<button className="ml-2 underline" onClick={() => window.location.reload()}>重新加载</button></main>;
    return this.props.children;
  }
}

function Page({ children }: { children: ReactNode }) {
  return <PageLoadBoundary><Suspense fallback={<main role="status" className="p-6">正在加载页面…</main>}>{children}</Suspense></PageLoadBoundary>;
}

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
  return user?.role === "admin" ? <Page><AdminPage /></Page> : <Navigate to="/" replace />;
}

function MoreRoute() {
  const location = useLocation();
  const status = (location.state as { status?: unknown } | null)?.status;
  return <>{status === "密码已更新" && <p className="mb-4 text-sm text-primary" role="status">密码已更新</p>}<Page><MorePage /></Page></>;
}

const routes: RouteObject[] = [{
  element: <AuthProvider><Outlet /></AuthProvider>,
  children: [
    { path: "/login", element: <Page><LoginPage /></Page> },
    { element: <ProtectedShell />, children: [
      { index: true, element: <Page><HomePage /></Page> },
      { path: "ledger", element: <Page><LedgerPage /></Page> },
      { path: "settlements", element: <Page><CompanySettlementPage /></Page> },
      { path: "database", element: <Page><BusinessRecordsPage /></Page> },
      { path: "more", element: <MoreRoute /> },
      { path: "account/password", element: <Page><AccountPasswordPage /></Page> },
      { path: "admin", element: <AdminRoute /> },
      { path: "ai", element: <Page><AgentChatPage /></Page> },
    ] },
  ],
}];

export function createAppRouter(initialEntries?: string[]) {
  return initialEntries ? createMemoryRouter(routes, { initialEntries }) : createBrowserRouter(routes);
}
