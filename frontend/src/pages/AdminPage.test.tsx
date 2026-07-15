import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { AdminPage } from "@/pages/AdminPage";
import { accessibleStoresKeyFor } from "@/stores/StoreProvider";

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

function renderAdmin() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { client, ...render(
    <QueryClientProvider client={client}>
      <AdminPage />
    </QueryClientProvider>,
  ) };
}

function activateTab(name: string) {
  const tab = screen.getByRole("tab", { name });
  fireEvent.mouseDown(tab, { button: 0, ctrlKey: false });
  fireEvent.mouseUp(tab, { button: 0, ctrlKey: false });
  fireEvent.click(tab);
}

describe("AdminPage", () => {
  it("offers all six administration areas", async () => {
    server.use(...emptyLists);
    renderAdmin();

    expect(await screen.findByRole("tab", { name: "用户" })).toBeInTheDocument();
    for (const name of ["门店", "成员", "收入分类", "告警", "任务日志"]) {
      expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    }
  });

  it("creates a user and refetches only the exact users list", async () => {
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
        return HttpResponse.json({ id: 3, username: "operator", role: "user", is_active: true }, { status: 201 });
      }),
    );
    renderAdmin();
    await waitFor(() => expect(userFetches).toBe(1));
    await waitFor(() => expect(storeFetches).toBe(1));

    fireEvent.change(screen.getByLabelText("新用户名"), { target: { value: "operator" } });
    fireEvent.change(screen.getByLabelText("初始密码"), { target: { value: "password-123" } });
    fireEvent.click(screen.getByRole("button", { name: "添加用户" }));

    await waitFor(() => expect(userFetches).toBe(2));
    expect(storeFetches).toBe(1);
    expect(posted).toEqual({ username: "operator", password: "password-123", role: "user" });
  });

  it("shows an API authorization error", async () => {
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json({ detail: "Admin access required" }, { status: 403 })),
      ...emptyLists.slice(1),
    );
    renderAdmin();

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
    renderAdmin();
    await screen.findByRole("tab", { name: "门店" });
    activateTab("门店");
    fireEvent.change(await screen.findByLabelText("门店名称"), { target: { value: "Roma" } });
    fireEvent.change(screen.getByLabelText("地址"), { target: { value: "Via Uno" } });
    fireEvent.change(screen.getByLabelText("纬度"), { target: { value: "41.9" } });
    fireEvent.change(screen.getByLabelText("经度"), { target: { value: "12.5" } });
    fireEvent.click(screen.getByRole("button", { name: "添加门店" }));

    await waitFor(() => expect(storeFetches).toBe(2));
    expect(posted).toEqual({ name: "Roma", address: "Via Uno", latitude: 41.9, longitude: 12.5, timezone: "Europe/Rome" });
  });

  it("loads and replaces members for a selected store, then refetches that exact member list", async () => {
    let memberFetches = 0;
    let replaced: unknown;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([
        { id: 1, username: "admin", role: "admin", is_active: true },
        { id: 2, username: "operator", role: "user", is_active: true },
      ])),
      http.get("/api/admin/stores", () => HttpResponse.json([
        { id: 9, name: "Roma", address: "Via Uno", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true },
      ])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.get("/api/admin/stores/9/members", () => {
        memberFetches += 1;
        return HttpResponse.json([{ id: 1, username: "admin", role: "admin", is_active: true }]);
      }),
      http.put("/api/admin/stores/9/members", async ({ request }) => {
        replaced = await request.json();
        return HttpResponse.json({ store_id: 9, user_ids: [1, 2] });
      }),
    );
    const { client } = renderAdmin();
    client.setQueryData(scopedAccessibleStoresKey, [{ id: 9 }]);
    await screen.findByRole("tab", { name: "成员" });
    activateTab("成员");
    fireEvent.change(await screen.findByLabelText("成员门店"), { target: { value: "9" } });
    await waitFor(() => expect(screen.getByLabelText("admin")).toBeChecked());
    fireEvent.click(screen.getByLabelText("operator"));
    fireEvent.click(screen.getByRole("button", { name: "保存成员" }));

    await waitFor(() => expect(memberFetches).toBe(2));
    expect(replaced).toEqual({ user_ids: [1, 2] });
    expect(client.getQueryState(scopedAccessibleStoresKey)?.isInvalidated).toBe(true);
  });

  it("prevents replacing members when the current member list failed to load", async () => {
    let puts = 0;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([{ id: 1, username: "admin", role: "admin", is_active: true }])),
      http.get("/api/admin/stores", () => HttpResponse.json([{ id: 9, name: "Roma", address: "Via Uno", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true }])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.get("/api/admin/stores/9/members", () => HttpResponse.json({ detail: "Members unavailable" }, { status: 500 })),
      http.put("/api/admin/stores/9/members", () => { puts += 1; return HttpResponse.json({ store_id: 9, user_ids: [] }); }),
    );
    renderAdmin();
    await screen.findByRole("tab", { name: "成员" });
    activateTab("成员");
    fireEvent.change(await screen.findByLabelText("成员门店"), { target: { value: "9" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Members unavailable");
    const save = screen.getByRole("button", { name: "保存成员" });
    expect(save).toBeDisabled();
    fireEvent.submit(save.closest("form")!);
    expect(puts).toBe(0);
  });

  it("prevents replacing members when the user list failed to load", async () => {
    let puts = 0;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json({ detail: "Users unavailable" }, { status: 500 })),
      http.get("/api/admin/stores", () => HttpResponse.json([{ id: 9, name: "Roma", address: "Via Uno", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true }])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.get("/api/admin/stores/9/members", () => HttpResponse.json([])),
      http.put("/api/admin/stores/9/members", () => { puts += 1; return HttpResponse.json({ store_id: 9, user_ids: [] }); }),
    );
    renderAdmin();
    await screen.findByRole("tab", { name: "成员" });
    activateTab("成员");
    fireEvent.change(await screen.findByLabelText("成员门店"), { target: { value: "9" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "保存成员" })).toBeDisabled());
    fireEvent.submit(screen.getByRole("button", { name: "保存成员" }).closest("form")!);
    expect(puts).toBe(0);
  });

  it("loads and creates categories for a selected store, then refetches that exact category list", async () => {
    let categoryFetches = 0;
    let posted: unknown;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([])),
      http.get("/api/admin/stores", () => HttpResponse.json([
        { id: 9, name: "Roma", address: "Via Uno", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true },
      ])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.get("/api/admin/income-categories", ({ request }) => {
        expect(new URL(request.url).searchParams.get("store_id")).toBe("9");
        categoryFetches += 1;
        return HttpResponse.json([]);
      }),
      http.post("/api/admin/income-categories", async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json({ id: 4, store_id: 9, name: "现金", include_in_total: true, is_active: true, sort_order: 2 }, { status: 201 });
      }),
    );
    renderAdmin();
    await screen.findByRole("tab", { name: "收入分类" });
    activateTab("收入分类");
    fireEvent.change(await screen.findByLabelText("分类门店"), { target: { value: "9" } });
    fireEvent.change(await screen.findByLabelText("分类名称"), { target: { value: "现金" } });
    fireEvent.change(screen.getByLabelText("排序"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "添加分类" }));

    await waitFor(() => expect(categoryFetches).toBe(2));
    expect(posted).toEqual({ store_id: 9, name: "现金", include_in_total: true, sort_order: 2 });
  });

  it("edits users and exposes their operation history", async () => {
    let patch: unknown;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([{ id: 2, username: "operator", role: "user", is_active: true }])),
      http.get("/api/admin/stores", () => HttpResponse.json([])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.patch("/api/admin/users/2", async ({ request }) => { patch = await request.json(); return HttpResponse.json({ id: 2, username: "operator", role: "user", is_active: false }); }),
      http.get("/api/admin/users/2/operations", () => HttpResponse.json([{ id: 7, description: "Updated ledger", operation_type: "update", created_at: "2026-07-14T10:00:00" }])),
    );
    renderAdmin();
    await screen.findByText("operator");
    fireEvent.click(screen.getByRole("button", { name: "停用用户 operator" }));
    await waitFor(() => expect(patch).toEqual({ is_active: false }));
    fireEvent.change(screen.getByLabelText("新密码 operator"), { target: { value: "new-password" } });
    fireEvent.click(screen.getByRole("button", { name: "修改密码 operator" }));
    await waitFor(() => expect(patch).toEqual({ password: "new-password" }));
    fireEvent.click(screen.getByRole("button", { name: "操作历史 operator" }));
    expect(await screen.findByText("Updated ledger")).toBeInTheDocument();
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
    const { client } = renderAdmin();
    client.setQueryData(scopedAccessibleStoresKey, [{ id: 9 }]);
    client.setQueryData(["dashboard", 10], { untouched: true });
    activateTab("门店");
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
    const { client } = renderAdmin();
    client.setQueryData(scopedAccessibleStoresKey, [{ id: 9 }]);
    activateTab("门店");
    await screen.findByRole("button", { name: "停用门店 Roma" });
    fireEvent.change(screen.getByLabelText("门店名称"), { target: { value: "Milano" } });
    fireEvent.change(screen.getByLabelText("地址"), { target: { value: "Via Due" } });
    fireEvent.change(screen.getByLabelText("纬度"), { target: { value: "45.4" } });
    fireEvent.change(screen.getByLabelText("经度"), { target: { value: "9.2" } });
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
      http.get("/api/admin/users", () => HttpResponse.json([{ id: 2, username: "operator", role: "user", is_active: true }])),
      http.get("/api/admin/stores", () => HttpResponse.json([])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.patch("/api/admin/users/2", async () => { await delayed; return HttpResponse.json({ detail: "Edit rejected" }, { status: 409 }); }),
    );
    renderAdmin();
    const toggle = await screen.findByRole("button", { name: "停用用户 operator" });
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toBeDisabled());
    expect(screen.getByRole("button", { name: "修改密码 operator" })).toBeDisabled();
    reject();
    expect(await screen.findByRole("alert")).toHaveTextContent("Edit rejected");
  });

  it("edits category behavior and invalidates only the affected store data", async () => {
    let patch: unknown;
    server.use(
      http.get("/api/admin/users", () => HttpResponse.json([])),
      http.get("/api/admin/stores", () => HttpResponse.json([{ id: 9, name: "Roma", address: "Via", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true }])),
      http.get("/api/admin/alerts", () => HttpResponse.json([])),
      http.get("/api/admin/task-logs", () => HttpResponse.json([])),
      http.get("/api/admin/income-categories", () => HttpResponse.json([{ id: 4, store_id: 9, name: "现金", include_in_total: true, is_active: true, sort_order: 2 }])),
      http.patch("/api/admin/income-categories/4", async ({ request }) => { patch = await request.json(); return HttpResponse.json({ id: 4, store_id: 9, name: "现金", include_in_total: false, is_active: true, sort_order: 1 }); }),
    );
    const { client } = renderAdmin();
    client.setQueryData(["dashboard", 9], []); client.setQueryData(["dashboard", 10], []);
    client.setQueryData(["charts", 9, ""], {}); client.setQueryData(["database", "records", 9, ""], {});
    activateTab("收入分类");
    await screen.findByRole("option", { name: "Roma" });
    fireEvent.change(await screen.findByLabelText("分类门店"), { target: { value: "9" } });
    await screen.findByLabelText("计入总收入 现金");
    fireEvent.click(screen.getByLabelText("计入总收入 现金"));
    fireEvent.change(screen.getByLabelText("排序 现金"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "保存分类 现金" }));
    await waitFor(() => expect(patch).toMatchObject({ include_in_total: false, sort_order: 1 }));
    expect(client.getQueryState(["dashboard", 9])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["charts", 9, ""])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["database", "records", 9, ""])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["dashboard", 10])?.isInvalidated).toBe(false);
  });
});
