import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";

import { UsersPanel } from "@/admin/UsersPanel";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { server.resetHandlers(); vi.restoreAllMocks(); });
afterAll(() => server.close());

function renderPanel(selectedStoreId: number | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><UsersPanel selectedStoreId={selectedStoreId} onSelectedStoreChange={() => undefined} /></QueryClientProvider>);
}

it("shows role, accessible stores, active state and ordinary-user guidance", async () => {
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([
      { id: 1, username: "boss", role: "admin", is_active: true, store_ids: [] },
      { id: 2, username: "operator", role: "user", is_active: true, store_ids: [9] },
    ])),
    http.get("/api/admin/stores", () => HttpResponse.json([
      { id: 9, name: "Roma", address: "Via", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true },
      { id: 10, name: "Milano", address: "Via", latitude: "45.4", longitude: "9.2", timezone: "Europe/Rome", is_active: true },
    ])),
  );
  renderPanel();

  expect(await screen.findByText("普通用户看不到管理中心，只能使用已分配门店的日常经营页面。")).toBeInTheDocument();
  await screen.findByText("boss");
  expect(screen.getByText(/可访问门店：全部门店/)).toBeInTheDocument();
  expect(screen.getByText(/可访问门店：Roma/)).toBeInTheDocument();
  expect(screen.getAllByText(/· 启用/)).toHaveLength(2);
});

it("edits a normal user's role, stores and password inline while hiding admin store choices", async () => {
  let operatorPatch: unknown;
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([
      { id: 1, username: "boss", role: "admin", is_active: true, store_ids: [] },
      { id: 2, username: "operator", role: "user", is_active: true, store_ids: [9] },
    ])),
    http.get("/api/admin/stores", () => HttpResponse.json([
      { id: 9, name: "Roma", address: "Via", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true },
      { id: 10, name: "Milano", address: "Via", latitude: "45.4", longitude: "9.2", timezone: "Europe/Rome", is_active: true },
    ])),
    http.patch("/api/admin/users/2", async ({ request }) => {
      operatorPatch = await request.json();
      return HttpResponse.json({ id: 2, username: "operator", role: "user", is_active: true, store_ids: [9, 10] });
    }),
  );
  renderPanel();
  await screen.findByText("operator");

  expect(screen.queryByLabelText("boss 可访问 Roma")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "编辑用户 operator" }));
  fireEvent.click(screen.getByLabelText("operator 可访问 Milano"));
  fireEvent.change(screen.getByLabelText("重置密码 operator"), { target: { value: "new-password" } });
  fireEvent.click(screen.getByRole("button", { name: "保存用户 operator" }));

  await waitFor(() => expect(operatorPatch).toEqual({ role: "user", is_active: true, store_ids: [9, 10], password: "new-password" }));
});

it("permanently deletes only after confirmation and refreshes the user list", async () => {
  let users = [{ id: 2, username: "mistake", role: "user", is_active: true, store_ids: [] }];
  let fetches = 0;
  let deletes = 0;
  vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  server.use(
    http.get("/api/admin/users", () => { fetches += 1; return HttpResponse.json(users); }),
    http.get("/api/admin/stores", () => HttpResponse.json([])),
    http.delete("/api/admin/users/2", () => { deletes += 1; users = []; return new HttpResponse(null, { status: 204 }); }),
  );
  renderPanel();
  await screen.findByText("mistake");

  fireEvent.click(screen.getByRole("button", { name: "永久删除用户 mistake" }));
  expect(deletes).toBe(0);
  fireEvent.click(screen.getByRole("button", { name: "永久删除用户 mistake" }));

  await waitFor(() => expect(fetches).toBe(2));
  await waitFor(() => expect(screen.queryByText("mistake")).not.toBeInTheDocument());
  expect(window.confirm).toHaveBeenCalled();
});

it("guides the administrator to deactivate a user when deletion returns 409", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([{ id: 2, username: "used", role: "user", is_active: true, store_ids: [] }])),
    http.get("/api/admin/stores", () => HttpResponse.json([])),
    http.delete("/api/admin/users/2", () => HttpResponse.json({ detail: "该用户已有历史记录，不能永久删除；请停用账号" }, { status: 409 })),
  );
  renderPanel();
  await screen.findByText("used");

  fireEvent.click(screen.getByRole("button", { name: "永久删除用户 used" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("有历史记录，只能停用账号");
});

it("never shows or submits administrators in the legacy store member editor", async () => {
  let replaced: unknown;
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([
      { id: 1, username: "boss", role: "admin", is_active: true, store_ids: [] },
      { id: 2, username: "operator", role: "user", is_active: true, store_ids: [9] },
    ])),
    http.get("/api/admin/stores", () => HttpResponse.json([{ id: 9, name: "Roma", address: "Via", latitude: "41", longitude: "12", timezone: "Europe/Rome", is_active: true }])),
    http.get("/api/admin/stores/9/members", () => HttpResponse.json([
      { id: 1, username: "boss", role: "admin", is_active: true },
      { id: 2, username: "operator", role: "user", is_active: true },
    ])),
    http.put("/api/admin/stores/9/members", async ({ request }) => { replaced = await request.json(); return HttpResponse.json({ store_id: 9, user_ids: [2] }); }),
  );
  renderPanel(9);
  await screen.findByLabelText("operator");

  expect(screen.queryByLabelText("boss")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "保存成员" }));
  await waitFor(() => expect(replaced).toEqual({ user_ids: [2] }));
});

it("resets the edit draft from the latest user state before editing", async () => {
  let active = true;
  const patches: unknown[] = [];
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([{ id: 2, username: "operator", role: "user", is_active: active, store_ids: [9] }])),
    http.get("/api/admin/stores", () => HttpResponse.json([
      { id: 9, name: "Roma", address: "Via", latitude: "41", longitude: "12", timezone: "Europe/Rome", is_active: true },
      { id: 10, name: "Milano", address: "Via", latitude: "45", longitude: "9", timezone: "Europe/Rome", is_active: true },
    ])),
    http.patch("/api/admin/users/2", async ({ request }) => {
      const body = await request.json() as { is_active?: boolean; store_ids?: number[] };
      patches.push(body);
      if (body.store_ids === undefined && body.is_active !== undefined) active = body.is_active;
      return HttpResponse.json({ id: 2, username: "operator", role: "user", is_active: active, store_ids: body.store_ids ?? [9] });
    }),
  );
  renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: "停用用户 operator" }));
  await screen.findByRole("button", { name: "启用用户 operator" });

  fireEvent.click(screen.getByRole("button", { name: "编辑用户 operator" }));
  fireEvent.click(screen.getByLabelText("operator 可访问 Milano"));
  fireEvent.click(screen.getByRole("button", { name: "保存用户 operator" }));

  await waitFor(() => expect(patches.at(-1)).toMatchObject({ is_active: false, store_ids: [9, 10] }));
});

it("shows truthful loading and error states for accessible stores", async () => {
  let resolveStores!: (response: HttpResponse<null>) => void;
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([{ id: 2, username: "operator", role: "user", is_active: true, store_ids: [] }])),
    http.get("/api/admin/stores", () => new Promise<HttpResponse<null>>((resolve) => { resolveStores = resolve; })),
  );
  const first = renderPanel();
  await screen.findByText("operator");
  expect(screen.getByText(/可访问门店：加载中/)).toBeInTheDocument();
  first.unmount();
  resolveStores(new HttpResponse(null, { status: 499 }));

  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([{ id: 2, username: "operator", role: "user", is_active: true, store_ids: [] }])),
    http.get("/api/admin/stores", () => HttpResponse.json({ detail: "failed" }, { status: 500 })),
  );
  renderPanel();
  await screen.findByText("operator");
  expect(await screen.findByText(/可访问门店：暂时无法获取/)).toBeInTheDocument();
  expect(screen.queryByText(/可访问门店：未分配门店/)).not.toBeInTheDocument();
});

it("marks inactive assignments but does not offer them in the editor", async () => {
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([{ id: 2, username: "operator", role: "user", is_active: true, store_ids: [10] }])),
    http.get("/api/admin/stores", () => HttpResponse.json([
      { id: 9, name: "Roma", address: "Via", latitude: "41", longitude: "12", timezone: "Europe/Rome", is_active: true },
      { id: 10, name: "Closed", address: "Via", latitude: "45", longitude: "9", timezone: "Europe/Rome", is_active: false },
    ])),
  );
  renderPanel();
  await screen.findByText(/可访问门店：Closed（已停用）/);
  fireEvent.click(screen.getByRole("button", { name: "编辑用户 operator" }));
  expect(screen.queryByLabelText("operator 可访问 Closed")).not.toBeInTheDocument();
});
