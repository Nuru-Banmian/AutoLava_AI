import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { PropsWithChildren } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { RouterProvider } from "react-router-dom";

import { StoreProvider, useStore } from "@/stores/StoreProvider";
import { createAppRouter } from "@/router";
import { AuthProvider, useAuth } from "@/auth/AuthProvider";

const admin = { id: 1, username: "admin", role: "admin" as const, is_owner: false };
const member = { id: 2, username: "member", role: "user" as const, is_owner: false };

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

function OwnerLoginProbe() {
  const { user, login } = useAuth();
  if (user) return <span>owner:{String(user.is_owner)}</span>;
  return <button type="button" onClick={() => void login({ username: "owner", password: "long-password" })}>probe login</button>;
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

  it("keeps the login form hidden until a delayed authenticated session resolves", async () => {
    let resolveMe!: () => void;
    server.use(
      http.get("/api/auth/me", async () => {
        await new Promise<void>((resolve) => { resolveMe = resolve; });
        return HttpResponse.json(admin);
      }),
      http.get("/api/stores/accessible", () => HttpResponse.json([])),
    );
    renderTestRouter("/login");

    expect(screen.getByRole("status")).toHaveTextContent("正在加载");
    expect(screen.queryByLabelText("用户名")).not.toBeInTheDocument();
    await waitFor(() => expect(resolveMe).toBeDefined());
    resolveMe();
    expect(await screen.findByRole("heading", { name: "仪表盘" })).toBeInTheDocument();
  });

  it("shows the login form only after a delayed session check returns 401", async () => {
    let resolveMe!: () => void;
    server.use(http.get("/api/auth/me", async () => {
      await new Promise<void>((resolve) => { resolveMe = resolve; });
      return HttpResponse.json({ detail: "Authentication required" }, { status: 401 });
    }));
    renderTestRouter("/login");

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByLabelText("用户名")).not.toBeInTheDocument();
    await waitFor(() => expect(resolveMe).toBeDefined());
    resolveMe();
    expect(await screen.findByLabelText("用户名")).toBeInTheDocument();
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

  it("sends only username and password and opens the authenticated shell after login", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("heading", { name: "仪表盘" })).toBeInTheDocument();
    expect(loginBody).toEqual({ username: "admin", password: "long-password" });
  });

  it("keeps the owner flag from the login response without refetching the session", async () => {
    let sessionFetches = 0;
    server.use(
      http.get("/api/auth/me", () => {
        sessionFetches += 1;
        return HttpResponse.json({ detail: "Authentication required" }, { status: 401 });
      }),
      http.post("/api/auth/login", () => HttpResponse.json({
        id: 1,
        username: "owner",
        role: "admin",
        is_owner: true,
      })),
    );
    render(<QueryWrapper><AuthProvider><OwnerLoginProbe /></AuthProvider></QueryWrapper>);

    fireEvent.click(await screen.findByRole("button", { name: "probe login" }));

    expect(await screen.findByText("owner:true")).toBeInTheDocument();
    expect(sessionFetches).toBe(1);
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

  it("keeps the session and shows a retryable error when logout fails", async () => {
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json(admin)),
      http.get("/api/stores/accessible", () => HttpResponse.json([])),
      http.post("/api/auth/logout", () => HttpResponse.json({ detail: "Logout unavailable" }, { status: 500 })),
    );
    renderTestRouter("/");

    fireEvent.click(await screen.findByRole("button", { name: "退出登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("退出失败，请重试");
    expect(screen.getByRole("heading", { name: "仪表盘" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "退出登录" })).toBeEnabled();
  });

  it("does not expose the previous user's cached stores while the next user's stores load", async () => {
    let resolveSecondStores!: () => void;
    let secondStoresRequested = false;
    let memberLoggedIn = false;
    const secondStores = new Promise<void>((resolve) => { resolveSecondStores = resolve; });
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json(admin)),
      http.get("/api/stores/accessible", async () => {
        if (!memberLoggedIn) {
          return HttpResponse.json([{ id: 7, name: "Admin Store", timezone: "Europe/Rome" }]);
        }
        secondStoresRequested = true;
        await secondStores;
        return HttpResponse.json([{ id: 8, name: "Member Store", timezone: "Europe/Rome" }]);
      }),
      http.get("/api/dashboard/:storeId", () => HttpResponse.json([])),
      http.post("/api/auth/logout", () => new HttpResponse(null, { status: 204 })),
      http.post("/api/auth/login", () => { memberLoggedIn = true; return HttpResponse.json(member); }),
    );
    renderTestRouter("/");
    const desktopPicker = await screen.findByTestId("desktop-store-picker");
    expect(await within(desktopPicker).findByRole("option", { name: "Admin Store" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    fireEvent.change(await screen.findByLabelText("用户名"), { target: { value: "member" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "long-password" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => expect(secondStoresRequested).toBe(true));
    expect(screen.queryAllByRole("option", { name: "Admin Store" })).toHaveLength(0);
    const memberDesktopPicker = screen.getByTestId("desktop-store-picker");
    expect(within(memberDesktopPicker).getByRole("combobox", { name: "门店" })).toHaveValue("");
    resolveSecondStores();
    expect(await within(memberDesktopPicker).findByRole("option", { name: "Member Store" })).toBeInTheDocument();
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

  it("distinguishes a store loading failure from an empty list and retries", async () => {
    let requests = 0;
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json(admin)),
      http.get("/api/stores/accessible", () => {
        requests += 1;
        if (requests === 1) return HttpResponse.json({ detail: "Stores unavailable" }, { status: 500 });
        return HttpResponse.json([{ id: 7, name: "Recovered Store", timezone: "Europe/Rome" }]);
      }),
    );
    renderTestRouter("/");

    expect(await screen.findByRole("alert")).toHaveTextContent("门店加载失败，请重试");
    const desktopPicker = screen.getByTestId("desktop-store-picker");
    expect(within(desktopPicker).getByRole("combobox", { name: "门店" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "重试门店" }));
    expect(await within(desktopPicker).findByRole("option", { name: "Recovered Store" })).toBeInTheDocument();
    expect(requests).toBe(2);
  });

  it("hides admin navigation and redirects a non-admin from the admin route", async () => {
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json(member)),
      http.get("/api/stores/accessible", () => HttpResponse.json([])),
    );
    renderTestRouter("/admin");

    expect(await screen.findByRole("heading", { name: "仪表盘" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "管理中心" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "系统管理" })).not.toBeInTheDocument();
  });

  it("renders the role-aware desktop and mobile navigation", async () => {
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json(admin)),
      http.get("/api/stores/accessible", () => HttpResponse.json([])),
    );
    renderTestRouter("/");

    const desktop = await screen.findByRole("navigation", { name: "主导航" });
    const mobile = screen.getByRole("navigation", { name: "移动导航" });
    expect(desktop.closest("aside")).toHaveClass("hidden", "md:flex");
    expect(mobile).toHaveClass("fixed", "md:hidden");
    expect(within(desktop).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "首页",
      "每日记账",
      "营业记录",
      "管理中心",
    ]);
    expect(within(mobile).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "首页",
      "记账",
      "记录",
      "更多",
    ]);
  });
});
