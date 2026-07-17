import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/auth/AuthProvider";
import { UnsavedChangesProvider } from "@/navigation/UnsavedChanges";
import { AdminPage } from "@/pages/AdminPage";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: vi.fn() }));

const server = setupServer();
const emptyLists = [
  http.get("/api/admin/users", () => HttpResponse.json([])),
  http.get("/api/admin/stores", () => HttpResponse.json([])),
  http.get("/api/admin/alerts", () => HttpResponse.json([])),
  http.get("/api/admin/task-logs", () => HttpResponse.json([])),
];

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  vi.mocked(useAuth).mockReturnValue({
    user: { id: 1, username: "admin", role: "admin", is_owner: true },
    isLoading: false,
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    isLoggingIn: false,
    isLoggingOut: false,
    logoutError: null,
  });
});
afterEach(() => {
  server.resetHandlers();
  vi.clearAllMocks();
});
afterAll(() => server.close());

function renderAdmin(initialEntry = "/admin") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={client}>
        <UnsavedChangesProvider><AdminPage /></UnsavedChangesProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("AdminPage", () => {
  it("shows the current three administration areas and defaults to stores", async () => {
    server.use(...emptyLists);
    renderAdmin();

    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["门店与收入", "用户与权限", "系统状态"]);
    expect(screen.getByRole("tab", { name: "门店与收入" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "新建门店" })).toBeInTheDocument();
  });

  it("selects requested panels and falls back to stores for invalid tabs", async () => {
    server.use(...emptyLists);
    const first = renderAdmin("/admin?tab=status");
    expect(screen.getByRole("tab", { name: "系统状态" })).toHaveAttribute("aria-selected", "true");
    first.unmount();

    const second = renderAdmin("/admin?tab=users");
    expect(screen.getByRole("tab", { name: "用户与权限" })).toHaveAttribute("aria-selected", "true");
    second.unmount();

    renderAdmin("/admin?tab=unknown");
    expect(screen.getByRole("tab", { name: "门店与收入" })).toHaveAttribute("aria-selected", "true");
  });
});
