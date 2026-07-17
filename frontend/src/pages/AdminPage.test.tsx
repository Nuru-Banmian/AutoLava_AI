import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/auth/AuthProvider";
import { UnsavedChangesProvider } from "@/navigation/UnsavedChanges";
import { AdminPage } from "@/pages/AdminPage";
import { accessibleStoresKeyFor } from "@/stores/StoreProvider";

vi.mock("@/components/StoreLocationPicker", () => ({
  StoreLocationPicker: ({ value, onConfirm }: { value: unknown; onConfirm: (location: unknown) => void }) => (
    <button type="button" onClick={() => onConfirm({ label: "Via Uno", latitude: 41.9, longitude: 12.5, timezone: "Europe/Rome" })}>
      {value ? "修改地图位置" : "打开地图选择"}
    </button>
  ),
}));

const server = setupServer();
const scopedAccessibleStoresKey = accessibleStoresKeyFor(1);

const emptyLists = [
  http.get("/api/admin/users", () => HttpResponse.json([])),
  http.get("/api/admin/stores", () => HttpResponse.json([])),
  http.get("/api/admin/alerts", () => HttpResponse.json([])),
  http.get("/api/admin/task-logs", () => HttpResponse.json([])),
];

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderAdmin(initialEntry = "/admin") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { client, ...render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={client}>
        <AdminPage />
      </QueryClientProvider>
    </MemoryRouter>,
  ) };
}

function renderUserAdmin(initialEntry = "/admin?tab=users") {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({
    id: 1,
    username: "Nuru_Banmian",
    role: "admin",
    is_owner: true,
  })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { client, ...render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={client}>
        <AuthProvider>
          <UnsavedChangesProvider><AdminPage /></UnsavedChangesProvider>
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  ) };
}

describe("AdminPage", () => {
  it("shows the four administration areas in the approved order and defaults to income", async () => {
    server.use(...emptyLists);
    renderAdmin();

    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["收入项目", "用户与权限", "门店设置", "系统状态"]);
    expect(screen.getByRole("tab", { name: "收入项目" })).toHaveAttribute("aria-selected", "true");
  });

  it("selects a panel from the tab query and safely falls back for invalid values", async () => {
    server.use(...emptyLists);
    const first = renderAdmin("/admin?tab=status");
    expect(screen.getByRole("tab", { name: "系统状态" })).toHaveAttribute("aria-selected", "true");
    first.unmount();

    renderAdmin("/admin?tab=unknown");
    expect(screen.getByRole("tab", { name: "收入项目" })).toHaveAttribute("aria-selected", "true");
  });

  it("creates a user from the user workspace and refetches the users list", async () => {
    let userFetches = 0;
    let storeFetches = 0;
    let posted: unknown;
    server.use(
      http.get("/api/admin/users", () => {
        userFetches += 1;
        return HttpResponse.json([]);
      }),
      http.get("/api/admin/stores", () => {
        storeFetches += 1;
        return HttpResponse.json([]);
      }),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.post("/api/admin/users", async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json({ id: 3, username: "operator", role: "user", is_active: true, store_ids: [] }, { status: 201 });
      }),
    );
    renderUserAdmin();
    await waitFor(() => expect(userFetches).toBe(1));
    await waitFor(() => expect(storeFetches).toBe(1));

    fireEvent.click(screen.getByRole("button", { name: "新建用户" }));
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "operator" } });
    fireEvent.change(screen.getByLabelText("初始密码"), { target: { value: "password-123" } });
    fireEvent.click(screen.getByRole("button", { name: "添加用户" }));

    await waitFor(() => expect(userFetches).toBe(2));
    expect(storeFetches).toBe(1);
    expect(posted).toEqual({ username: "operator", password: "password-123", role: "user", store_ids: [] });
  });

  it("shows an API authorization error", async () => {
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json({ detail: "Admin access required" }, { status: 403 })),
      ...emptyLists.slice(1),
    );
    renderUserAdmin();

    expect(await screen.findByRole("alert")).toHaveTextContent("Admin access required");
  });

  it("creates a store using the backend contract and refetches the exact store list", async () => {
    let storeFetches = 0;
    let posted: unknown;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([])),
      http.get("/api/admin/stores", () => {
        storeFetches += 1;
        return HttpResponse.json([]);
      }),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.post("/api/admin/stores", async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json({ id: 9, name: "Roma", address: "Via Uno", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true }, { status: 201 });
      }),
    );
    renderAdmin("/admin?tab=stores");
    fireEvent.click(await screen.findByRole("button", { name: "新建门店" }));
    fireEvent.change(await screen.findByLabelText("门店名称"), { target: { value: "Roma" } });
    fireEvent.click(screen.getByRole("button", { name: "打开地图选择" }));
    fireEvent.click(screen.getByRole("button", { name: "添加门店" }));

    await waitFor(() => expect(storeFetches).toBe(2));
    expect(posted).toEqual({ name: "Roma", address: "Via Uno", latitude: 41.9, longitude: 12.5, timezone: "Europe/Rome" });
  });

  it("loads the current income config and publishes a local draft once", async () => {
    let published: unknown;
    let publishCount = 0;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([])),
      http.get("/api/admin/stores", () => HttpResponse.json([
        { id: 9, name: "Roma", address: "Via Uno", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true },
      ])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.get("/api/income-config/9/current", () => HttpResponse.json({ store_id: 9, version_id: null, version: 0, enabled: false, formula: "总收入 = €0.00", created_at: null, items: [] })),
      http.get("/api/admin/income-categories", () => HttpResponse.json([])),
      http.put("/api/admin/stores/9/income-config", async ({ request }) => {
        publishCount += 1;
        published = await request.json();
        return HttpResponse.json({ store_id: 9, version_id: 1, version: 1, enabled: true, formula: "总收入 = 现金", created_at: "2026-07-16T10:00:00", items: [{ id: 1, category_id: 4, name: "现金", include_in_total: true, is_active: true, sort_order: 0 }] });
      }),
    );
    renderAdmin();
    await screen.findByRole("option", { name: "Roma" });
    fireEvent.change(await screen.findByLabelText("收入项目门店"), { target: { value: "9" } });
    const enabled = await screen.findByRole("checkbox", { name: "启用收入项目明细" });
    await waitFor(() => expect(enabled).toBeEnabled());
    fireEvent.click(enabled);
    fireEvent.change(await screen.findByLabelText("新收入项目名称"), { target: { value: "现金" } });
    fireEvent.click(screen.getByRole("button", { name: "添加收入项目" }));
    expect(publishCount).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "保存并发布" }));

    await waitFor(() => expect(publishCount).toBe(1));
    expect(published).toEqual({ enabled: true, items: [{ category_id: null, name: "现金", include_in_total: true, is_active: true, sort_order: 0 }] });
  });

  it("edits a selected user through the single workspace editor", async () => {
    let patch: unknown;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([{ id: 2, username: "operator", role: "user", is_active: true, store_ids: [] }])),
      http.get("/api/admin/stores", () => HttpResponse.json([])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.patch("/api/admin/users/2", async ({ request }) => {
        patch = await request.json();
        return HttpResponse.json({ id: 2, username: "operator", role: "user", is_active: false, store_ids: [] });
      }),
    );
    renderUserAdmin();
    fireEvent.click(await screen.findByRole("button", { name: /operator/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "账号启用" }));
    fireEvent.change(screen.getByLabelText("重置密码（可选）"), { target: { value: "new-password" } });
    fireEvent.click(screen.getByRole("button", { name: "保存用户" }));

    await waitFor(() => expect(patch).toEqual({
      role: "user",
      is_active: false,
      store_ids: [],
      password: "new-password",
    }));
    expect(screen.queryByText("用户操作历史")).not.toBeInTheDocument();
  });

  it("edits stores and invalidates accessible stores", async () => {
    let patch: unknown;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([])),
      http.get("/api/admin/stores", () => HttpResponse.json([{ id: 9, name: "Roma", address: "Via Uno", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true }])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.patch("/api/admin/stores/9", async ({ request }) => { patch = await request.json(); return HttpResponse.json({ id: 9, name: "Milano", address: "Via Due", latitude: "45.4", longitude: "9.2", timezone: "Europe/Rome", is_active: true }); }),
    );
    const { client } = renderAdmin("/admin?tab=stores");
    client.setQueryData(scopedAccessibleStoresKey, [{ id: 9 }]);
    client.setQueryData(["dashboard", 10], { untouched: true });
    fireEvent.change(await screen.findByLabelText("门店名称 Roma"), { target: { value: "Milano" } });
    fireEvent.click(screen.getByRole("button", { name: "保存门店 Roma" }));
    await waitFor(() => expect(patch).toMatchObject({ name: "Milano" }));
    expect(client.getQueryState(scopedAccessibleStoresKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(["dashboard", 10])?.isInvalidated).toBe(false);
  });

  it("invalidates the canonical accessible-store key after create and disable", async () => {
    let active = true;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([])),
      http.get("/api/admin/stores", () => HttpResponse.json([{ id: 9, name: "Roma", address: "Via", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: active }])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.post("/api/admin/stores", () => HttpResponse.json({ id: 10, name: "Milano", address: "Via Due", latitude: "45.4", longitude: "9.2", timezone: "Europe/Rome", is_active: true }, { status: 201 })),
      http.patch("/api/admin/stores/9", () => { active = false; return HttpResponse.json({ id: 9, name: "Roma", address: "Via", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: false }); }),
    );
    const { client } = renderAdmin("/admin?tab=stores");
    client.setQueryData(scopedAccessibleStoresKey, [{ id: 9 }]);
    await screen.findByRole("button", { name: "停用门店 Roma" });
    fireEvent.click(screen.getByRole("button", { name: "新建门店" }));
    fireEvent.change(screen.getByLabelText("门店名称"), { target: { value: "Milano" } });
    fireEvent.click(screen.getByRole("button", { name: "打开地图选择" }));
    fireEvent.click(screen.getByRole("button", { name: "添加门店" }));
    await waitFor(() => expect(client.getQueryState(scopedAccessibleStoresKey)?.isInvalidated).toBe(true));
    client.setQueryData(scopedAccessibleStoresKey, [{ id: 9 }]);
    fireEvent.click(screen.getByRole("button", { name: "停用门店 Roma" }));
    await waitFor(() => expect(active).toBe(false));
    expect(client.getQueryState(scopedAccessibleStoresKey)?.isInvalidated).toBe(true);
  });

  it("shows edit errors and disables related actions while pending", async () => {
    let reject!: () => void;
    const delayed = new Promise<void>((resolve) => { reject = resolve; });
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([{ id: 2, username: "operator", role: "user", is_active: true, store_ids: [] }])),
      http.get("/api/admin/stores", () => HttpResponse.json([])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.patch("/api/admin/users/2", async () => { await delayed; return HttpResponse.json({ detail: "Edit rejected" }, { status: 409 }); }),
    );
    renderUserAdmin();
    fireEvent.click(await screen.findByRole("button", { name: /operator/ }));
    fireEvent.change(screen.getByLabelText("重置密码（可选）"), { target: { value: "new-password" } });
    const save = screen.getByRole("button", { name: "保存用户" });
    fireEvent.click(save);
    await waitFor(() => expect(save).toBeDisabled());
    expect(screen.getByLabelText("重置密码（可选）")).toBeDisabled();
    expect(screen.getByRole("button", { name: "永久删除" })).toBeDisabled();
    reject();
    expect(await screen.findByRole("alert")).toHaveTextContent("Edit rejected");
  });

  it("publishes category behavior and invalidates only the affected store data", async () => {
    let published: unknown;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([])),
      http.get("/api/admin/stores", () => HttpResponse.json([{ id: 9, name: "Roma", address: "Via", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true }])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.get("/api/income-config/9/current", () => HttpResponse.json({ store_id: 9, version_id: 1, version: 1, enabled: true, formula: "总收入 = 现金", created_at: "2026-07-16T10:00:00", items: [{ id: 1, category_id: 4, name: "现金", include_in_total: true, is_active: true, sort_order: 0 }] })),
      http.get("/api/admin/income-categories", () => HttpResponse.json([{ id: 4, store_id: 9, name: "现金", include_in_total: true, is_active: true, sort_order: 0, archived_at: null }])),
      http.put("/api/admin/stores/9/income-config", async ({ request }) => { published = await request.json(); return HttpResponse.json({ store_id: 9, version_id: 2, version: 2, enabled: true, formula: "总收入 = €0.00", created_at: "2026-07-16T10:05:00", items: [{ id: 2, category_id: 4, name: "现金", include_in_total: false, is_active: true, sort_order: 0 }] }); }),
    );
    const { client } = renderAdmin();
    client.setQueryData(["dashboard", 9], []); client.setQueryData(["dashboard", 10], []);
    client.setQueryData(["charts", 9, ""], {}); client.setQueryData(["database", "records", 9, ""], {});
    await screen.findByRole("option", { name: "Roma" });
    fireEvent.change(await screen.findByLabelText("收入项目门店"), { target: { value: "9" } });
    await screen.findByLabelText("计入营业额 现金");
    fireEvent.click(screen.getByLabelText("计入营业额 现金"));
    fireEvent.click(screen.getByRole("button", { name: "保存并发布" }));
    await waitFor(() => expect(published).toEqual({ enabled: true, items: [{ category_id: 4, name: "现金", include_in_total: false, is_active: true, sort_order: 0 }] }));
    expect(client.getQueryState(["dashboard", 9])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["charts", 9, ""])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["database", "records", 9, ""])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["dashboard", 10])?.isInvalidated).toBe(false);
  });
});
