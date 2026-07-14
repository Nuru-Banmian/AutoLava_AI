import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { PropsWithChildren } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { RouterProvider } from "react-router-dom";

import { StoreProvider, useStore } from "@/stores/StoreProvider";
import { createAppRouter } from "@/router";

const admin = { id: 1, username: "admin", role: "admin" as const };
const member = { id: 2, username: "member", role: "user" as const };

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function createClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function renderTestRouter(path: string) {
  return render(
    <QueryClientProvider client={createClient()}>
      <RouterProvider router={createAppRouter([path])} />
    </QueryClientProvider>,
  );
}

function QueryWrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={createClient()}>{children}</QueryClientProvider>;
}

function StoreProbe() {
  const { selected } = useStore();
  return <span>selected:{selected?.id ?? "none"}</span>;
}

describe("authenticated application shell", () => {
  it("redirects unauthenticated visitors to login", async () => {
    server.use(
      http.get("/api/auth/me", () =>
        HttpResponse.json({ detail: "Authentication required" }, { status: 401 }),
      ),
    );

    renderTestRouter("/ledger");

    expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
  });

  it("redirects an already authenticated visitor away from login", async () => {
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json(admin)),
      http.get("/api/stores/accessible", () => HttpResponse.json([])),
    );

    renderTestRouter("/login");

    expect(await screen.findByRole("heading", { name: "仪表盘" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "登录" })).not.toBeInTheDocument();
  });

  it("does not flash protected content while authentication is loading", async () => {
    let resolveMe!: () => void;
    server.use(
      http.get("/api/auth/me", async () => {
        await new Promise<void>((resolve) => {
          resolveMe = resolve;
        });
        return HttpResponse.json(admin);
      }),
      http.get("/api/stores/accessible", () => HttpResponse.json([])),
    );

    renderTestRouter("/ledger");

    expect(screen.queryByRole("heading", { name: "每日台账" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("正在加载");
    await waitFor(() => expect(resolveMe).toBeDefined());
    resolveMe();
    expect(await screen.findByRole("heading", { name: "每日台账" })).toBeInTheDocument();
  });

  it("sends remember=true and opens the authenticated shell after login", async () => {
    let loginBody: unknown;
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json({ detail: "Authentication required" }, { status: 401 })),
      http.post("/api/auth/login", async ({ request }) => {
        loginBody = await request.json();
        return HttpResponse.json(admin);
      }),
      http.get("/api/stores/accessible", () => HttpResponse.json([])),
    );
    renderTestRouter("/login");

    fireEvent.change(await screen.findByLabelText("用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "long-password" } });
    fireEvent.click(screen.getByLabelText("记住我"));
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("heading", { name: "仪表盘" })).toBeInTheDocument();
    expect(loginBody).toEqual({ username: "admin", password: "long-password", remember: true });
  });

  it("logs out and returns to login", async () => {
    let loggedOut = false;
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json(admin)),
      http.get("/api/stores/accessible", () => HttpResponse.json([])),
      http.post("/api/auth/logout", () => {
        loggedOut = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderTestRouter("/");

    fireEvent.click(await screen.findByRole("button", { name: "退出登录" }));

    expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
    expect(loggedOut).toBe(true);
  });

  it("automatically selects the only accessible store", async () => {
    server.use(
      http.get("/api/stores/accessible", () =>
        HttpResponse.json([{ id: 7, name: "Lavaggio Roma", timezone: "Europe/Rome" }]),
      ),
    );

    render(
      <QueryWrapper>
        <StoreProvider>
          <StoreProbe />
        </StoreProvider>
      </QueryWrapper>,
    );

    expect(await screen.findByText("selected:7")).toBeInTheDocument();
  });

  it("hides admin navigation and redirects a non-admin from the admin route", async () => {
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json(member)),
      http.get("/api/stores/accessible", () => HttpResponse.json([])),
    );
    renderTestRouter("/admin");

    expect(await screen.findByRole("heading", { name: "仪表盘" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "管理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "系统管理" })).not.toBeInTheDocument();
  });

  it("renders responsive navigation and a disabled Phase 2 workers item", async () => {
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json(admin)),
      http.get("/api/stores/accessible", () => HttpResponse.json([])),
    );
    renderTestRouter("/");

    const desktop = await screen.findByRole("navigation", { name: "主导航" });
    const mobile = screen.getByRole("navigation", { name: "移动导航" });
    expect(desktop).toHaveClass("hidden", "md:flex");
    expect(mobile).toHaveClass("fixed", "md:hidden");
    expect(within(desktop).getByText("员工管理")).toHaveAttribute("aria-disabled", "true");
    expect(within(desktop).getByRole("link", { name: "管理" })).toBeInTheDocument();
  });
});
