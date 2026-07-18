import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { StrictMode, useState } from "react";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";

import { UsersPanel } from "@/admin/UsersPanel";
import type { AdminUser } from "@/api/types";
import { UnsavedChangesProvider, useUnsavedChanges } from "@/navigation/UnsavedChanges";
import { accessibleStoresKey } from "@/stores/StoreProvider";

const authState = vi.hoisted(() => ({
  user: { id: 1, username: "Nuru_Banmian", role: "admin" as const, is_owner: true },
}));

vi.mock("@/auth/AuthProvider", () => ({ useAuth: () => authState }));

const roma = { id: 9, name: "Roma", address: "Via Roma", latitude: "41.9",
  longitude: "12.5", timezone: "Europe/Rome", is_active: true };
const maria = { id: 2, username: "maria", role: "user" as const,
  is_active: true, store_ids: [9] };
const operator = { id: 3, username: "operator", role: "user" as const,
  is_active: true, store_ids: [] };

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  authState.user = { id: 1, username: "Nuru_Banmian", role: "admin", is_owner: true };
  vi.restoreAllMocks();
});
afterAll(() => server.close());

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false },
  } });
  const result = render(
    <QueryClientProvider client={client}>
      <UnsavedChangesProvider><UsersPanel /></UnsavedChangesProvider>
    </QueryClientProvider>,
  );
  return { ...result, client };
}

function renderStrictPanel(items: AdminUser[]) {
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false },
  } });
  client.setQueryData(["admin", "users"], items);
  client.setQueryData(["admin", "stores"], [roma]);
  const result = render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <UnsavedChangesProvider><UsersPanel /></UnsavedChangesProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
  return { ...result, client };
}

function UnmountHarness() {
  const [showPanel, setShowPanel] = useState(true);
  const [transitioned, setTransitioned] = useState(false);
  const { markDirty, requestTransition } = useUnsavedChanges();

  return <>
    {showPanel
      ? <><UsersPanel /><button type="button" onClick={() => setShowPanel(false)}>离开用户面板</button></>
      : <>
        <button type="button" onClick={() => markDirty(true)}>标记其他草稿</button>
        <button type="button" onClick={() => requestTransition(() => setTransitioned(true))}>离开其他草稿</button>
        <span>已离开：{String(transitioned)}</span>
      </>}
  </>;
}

function renderUnmountHarness() {
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false },
  } });
  const result = render(
    <QueryClientProvider client={client}>
      <UnsavedChangesProvider><UnmountHarness /></UnsavedChangesProvider>
    </QueryClientProvider>,
  );
  return { ...result, client };
}

function mockUsers(
  items: AdminUser[],
  captureCreate?: (request: Request) => Promise<void>,
) {
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json(items)),
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.post("/api/admin/users", async ({ request }) => {
      await captureCreate?.(request);
      return HttpResponse.json({ id: 10, username: "operator", role: "user",
        is_active: true, store_ids: [9] }, { status: 201 });
    }),
  );
}

it("selects the first user and exposes only existing users in the selector", async () => {
  mockUsers([maria, operator]);
  renderPanel();

  expect(await screen.findByRole("heading", { name: "编辑 maria" })).toBeInTheDocument();
  const selector = screen.getByRole("combobox", { name: "用户" });
  expect(selector).toHaveValue("2");
  expect(within(selector).getAllByRole("option").map((option) => option.textContent))
    .toEqual(["maria", "operator"]);
  expect(screen.queryByText("请选择用户", { selector: "p" })).not.toBeInTheDocument();
});

it("clears an auto-selected user's form and dirty navigation state after a Strict Mode save", async () => {
  mockUsers([maria]);
  server.use(http.patch("/api/admin/users/2", () => HttpResponse.json(maria)));
  renderStrictPanel([maria]);
  await screen.findByRole("heading", { name: "编辑 maria" });
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "replacement123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));

  await waitFor(() => expect(screen.getByRole("button", { name: "保存用户" })).toBeEnabled());
  expect(screen.getByLabelText("重置密码（可选）")).toHaveValue("");
  await userEvent.click(screen.getByRole("button", { name: "新建用户" }));
  expect(screen.queryByRole("alertdialog", { name: "放弃未保存的修改？" })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "新建用户" })).toBeInTheDocument();
});

it("keeps user controls on one row and leaves the selector blank in create mode", async () => {
  mockUsers([maria]);
  renderPanel();
  await screen.findByRole("heading", { name: "编辑 maria" });

  const controls = screen.getByTestId("user-panel-controls");
  expect(controls).toHaveClass("flex", "items-center");
  expect(within(controls).getByRole("combobox", { name: "用户" })).toBeInTheDocument();
  await userEvent.click(within(controls).getByRole("button", { name: "新建用户" }));

  const selector = within(controls).getByRole("combobox", { name: "用户" });
  expect(selector).toHaveValue("");
  expect(within(selector).queryByRole("option", { name: "新建用户" }))
    .not.toBeInTheDocument();
  expect(within(selector).queryByRole("option", { name: "请选择用户" }))
    .not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "添加用户" })).toBeInTheDocument();
});

it("does not invent a user selection for an empty list", async () => {
  mockUsers([]);
  renderPanel();

  const selector = await screen.findByRole("combobox", { name: "用户" });
  expect(selector).toHaveValue("");
  expect(screen.queryByText("请选择用户", { selector: "p" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: /^编辑 / })).not.toBeInTheDocument();
});

it("selects a newly created user", async () => {
  const created = { id: 10, username: "new-operator", role: "user" as const,
    is_active: true, store_ids: [9] };
  let users = [maria];
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json(users)),
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.post("/api/admin/users", () => {
      users = [maria, created];
      return HttpResponse.json(created, { status: 201 });
    }),
  );
  renderPanel();
  await screen.findByRole("heading", { name: "编辑 maria" });
  await userEvent.click(screen.getByRole("button", { name: "新建用户" }));
  await userEvent.type(screen.getByLabelText("用户名"), "new-operator");
  await userEvent.type(screen.getByLabelText("初始密码"), "operator123");
  await userEvent.click(screen.getByRole("checkbox", { name: "Roma" }));
  await userEvent.click(screen.getByRole("button", { name: "添加用户" }));

  expect(await screen.findByRole("heading", { name: "编辑 new-operator" })).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "用户" })).toHaveValue("10");
});

it("selects a user into one editor and removes duplicate management surfaces", async () => {
  mockUsers([
    { id: 2, username: "maria", role: "user", is_active: true, store_ids: [9] },
  ]);
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));

  expect(screen.getByRole("heading", { name: "编辑 maria" })).toBeInTheDocument();
  expect(screen.getAllByLabelText("重置密码（可选）")).toHaveLength(1);
  expect(screen.queryByText("门店成员")).not.toBeInTheDocument();
  expect(screen.queryByText("用户操作历史")).not.toBeInTheDocument();
  expect(screen.queryByText(/普通用户看不到管理中心/)).not.toBeInTheDocument();
  expect(screen.queryByText(/可访问 Roma/)).not.toBeInTheDocument();
});

it("renders administrators read-only for a non-owner", async () => {
  authState.user = { id: 3, username: "manager", role: "admin", is_owner: false };
  mockUsers([{ id: 4, username: "other-admin", role: "admin", is_active: true, store_ids: [] }]);
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /other-admin/ }));

  expect(screen.getByText("管理员账号只能由最终管理员编辑")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存用户" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "永久删除" })).not.toBeInTheDocument();
});

it("lets the owner edit another administrator", async () => {
  authState.user = { id: 1, username: "Nuru_Banmian", role: "admin", is_owner: true };
  mockUsers([{ id: 4, username: "other-admin", role: "admin", is_active: true, store_ids: [] }]);
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /other-admin/ }));

  expect(screen.getByRole("heading", { name: "编辑 other-admin" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存用户" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "永久删除" })).toBeInTheDocument();
  expect(screen.queryByLabelText("危险操作")).not.toBeInTheDocument();
  expect(screen.queryByText(/有历史记录.*只能停用/)).not.toBeInTheDocument();
  const footer = screen.getByTestId("user-editor-actions");
  expect(within(footer).getAllByRole("button").map((button) => button.textContent))
    .toEqual(["永久删除", "保存用户"]);
});

it("does not offer administrator creation to a non-owner", async () => {
  authState.user = { id: 3, username: "manager", role: "admin", is_owner: false };
  mockUsers([]);
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: "新建用户" }));

  expect(screen.getByRole("option", { name: "普通用户" })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "管理员" })).not.toBeInTheDocument();
});

it("guards user switches while the editor is dirty", async () => {
  authState.user = { id: 1, username: "Nuru_Banmian", role: "admin", is_owner: true };
  mockUsers([maria, operator]);
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "replacement123");
  await userEvent.click(screen.getByRole("button", { name: /operator/ }));

  expect(screen.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "继续编辑" }));
  expect(screen.getByRole("heading", { name: "编辑 maria" })).toBeInTheDocument();
});

it("keeps a dirty existing-user editor dirty when its selected rail item is clicked again", async () => {
  mockUsers([maria]);
  renderPanel();
  const mariaButton = await screen.findByRole("button", { name: /maria/ });
  await userEvent.click(mariaButton);
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "replacement123");

  await userEvent.click(mariaButton);

  expect(screen.queryByRole("alertdialog", { name: "放弃未保存的修改？" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("重置密码（可选）")).toHaveValue("replacement123");
  await userEvent.click(screen.getByRole("button", { name: "新建用户" }));
  expect(screen.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
});

it("keeps a dirty create editor dirty when the persistent new-user button is clicked again", async () => {
  mockUsers([maria]);
  renderPanel();
  const newUser = await screen.findByRole("button", { name: "新建用户" });
  await userEvent.click(newUser);
  await userEvent.type(screen.getByLabelText("用户名"), "operator");
  await userEvent.type(screen.getByLabelText("初始密码"), "operator123");

  await userEvent.click(newUser);

  expect(screen.queryByRole("alertdialog", { name: "放弃未保存的修改？" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("用户名")).toHaveValue("operator");
  await userEvent.click(screen.getByRole("button", { name: /maria/ }));
  expect(screen.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
});

it("creates a user with store access in the right-hand workspace", async () => {
  let posted: unknown;
  authState.user = { id: 1, username: "Nuru_Banmian", role: "admin", is_owner: true };
  mockUsers([], async (request) => { posted = await request.json(); });
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: "新建用户" }));
  await userEvent.type(screen.getByLabelText("用户名"), "operator");
  await userEvent.type(screen.getByLabelText("初始密码"), "operator123");
  await userEvent.click(screen.getByRole("checkbox", { name: "Roma" }));
  await userEvent.click(screen.getByRole("button", { name: "添加用户" }));

  await waitFor(() => expect(posted).toEqual({
    username: "operator",
    password: "operator123",
    role: "user",
    store_ids: [9],
  }));
});

it("preserves inactive and unknown memberships until they are explicitly removed", async () => {
  const patches: unknown[] = [];
  const assigned = { ...maria, store_ids: [9, 10, 77] };
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([assigned])),
    http.get("/api/admin/stores", () => HttpResponse.json([
      roma,
      { ...roma, id: 10, name: "Closed", is_active: false },
    ])),
    http.patch("/api/admin/users/2", async ({ request }) => {
      patches.push(await request.json());
      return HttpResponse.json(assigned);
    }),
  );
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));

  expect(screen.getByRole("checkbox", { name: /Closed.*已停用/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /未知门店.*77.*不可用/ })).toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));
  await waitFor(() => expect(patches[0]).toMatchObject({ store_ids: [9, 10, 77] }));

  await userEvent.click(screen.getByRole("checkbox", { name: /Closed.*已停用/ }));
  await userEvent.click(screen.getByRole("checkbox", { name: /未知门店.*77.*不可用/ }));
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));
  await waitFor(() => expect(patches[1]).toMatchObject({ store_ids: [9] }));
});

it("locks the submitted editor while its request is pending", async () => {
  const response = deferred<HttpResponse<AdminUser>>();
  mockUsers([maria]);
  server.use(http.patch("/api/admin/users/2", () => response.promise));
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "replacement123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));

  await waitFor(() => expect(screen.getByRole("button", { name: "保存用户" })).toBeDisabled());
  expect(screen.getByLabelText("重置密码（可选）")).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "Roma" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "永久删除" })).toBeDisabled();

  response.resolve(HttpResponse.json(maria));
  await waitFor(() => expect(screen.getByRole("button", { name: "保存用户" })).toBeEnabled());
  expect(screen.getByLabelText("重置密码（可选）")).toHaveValue("");
});

it("does not let a superseded user request initialize another user's editor", async () => {
  const mariaResponse = deferred<HttpResponse<AdminUser>>();
  mockUsers([maria, operator]);
  server.use(http.patch("/api/admin/users/2", () => mariaResponse.promise));
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "replacement123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));
  await userEvent.click(screen.getByRole("button", { name: /operator/ }));
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));

  expect(screen.getByRole("heading", { name: "编辑 operator" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存用户" })).toBeEnabled();
  mariaResponse.resolve(HttpResponse.json({ ...maria, store_ids: [] }));

  await waitFor(() => expect(screen.getByRole("heading", { name: "编辑 operator" })).toBeInTheDocument());
  expect(screen.getByLabelText("重置密码（可选）")).toHaveValue("");
  expect(screen.getByRole("checkbox", { name: "Roma" })).not.toBeChecked();
});

it("does not show a stale user error over a newer selection", async () => {
  const mariaResponse = deferred<HttpResponse<{ detail: string }>>();
  mockUsers([maria, operator]);
  server.use(http.patch("/api/admin/users/2", () => mariaResponse.promise));
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "replacement123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));
  await userEvent.click(screen.getByRole("button", { name: /operator/ }));
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
  mariaResponse.resolve(HttpResponse.json({ detail: "stale maria failure" }, { status: 409 }));

  await waitFor(() => expect(screen.getByRole("heading", { name: "编辑 operator" })).toBeInTheDocument());
  expect(screen.queryByText("stale maria failure")).not.toBeInTheDocument();
});

it("invalidates authoritative users and accessible stores for a superseded success", async () => {
  const mariaResponse = deferred<HttpResponse<AdminUser>>();
  let userFetches = 0;
  server.use(
    http.get("/api/admin/users", () => { userFetches += 1; return HttpResponse.json([maria, operator]); }),
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.patch("/api/admin/users/2", () => mariaResponse.promise),
  );
  const { client } = renderPanel();
  client.setQueryData(accessibleStoresKey, [{ id: 9, name: "Roma", timezone: "Europe/Rome" }]);
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "replacement123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));
  await userEvent.click(screen.getByRole("button", { name: /operator/ }));
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
  mariaResponse.resolve(HttpResponse.json(maria));

  await waitFor(() => expect(userFetches).toBe(2));
  expect(client.getQueryState(accessibleStoresKey)?.isInvalidated).toBe(true);
  expect(screen.getByRole("heading", { name: "编辑 operator" })).toBeInTheDocument();
});

it("does not clear another consumer's dirty state when an unmounted request succeeds", async () => {
  const mariaResponse = deferred<HttpResponse<AdminUser>>();
  mockUsers([maria]);
  server.use(http.patch("/api/admin/users/2", () => mariaResponse.promise));
  const { client } = renderUnmountHarness();
  client.setQueryData(accessibleStoresKey, [{ id: 9, name: "Roma", timezone: "Europe/Rome" }]);
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "replacement123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));
  await userEvent.click(screen.getByRole("button", { name: "离开用户面板" }));
  await userEvent.click(screen.getByRole("button", { name: "标记其他草稿" }));

  mariaResponse.resolve(HttpResponse.json(maria));

  await waitFor(() => expect(client.getQueryState(["admin", "users"])?.isInvalidated).toBe(true));
  expect(client.getQueryState(accessibleStoresKey)?.isInvalidated).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "离开其他草稿" }));
  expect(screen.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
  expect(screen.getByText("已离开：false")).toBeInTheDocument();
});

it("clears a dirty selection when the authoritative refetch removes it", async () => {
  let items = [maria];
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json(items)),
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.patch("/api/admin/users/2", () => {
      items = [];
      return HttpResponse.json(maria);
    }),
  );
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "replacement123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));

  await waitFor(() => {
    expect(screen.queryByRole("heading", { name: "编辑 maria" })).not.toBeInTheDocument();
  });
  expect(screen.queryByText("请选择用户", { selector: "p" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "新建用户" }));
  expect(screen.queryByRole("alertdialog", { name: "放弃未保存的修改？" })).not.toBeInTheDocument();
});

it("confirms permanent deletion in the editor footer and shows 409 guidance only after rejection", async () => {
  mockUsers([maria]);
  server.use(http.delete("/api/admin/users/2", () => HttpResponse.json(
    { detail: "该用户已有历史记录，不能永久删除；请停用账号" },
    { status: 409 },
  )));
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));

  expect(screen.queryByText(/有历史记录.*只能停用/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "永久删除" }));
  expect(screen.getByRole("alertdialog", { name: "永久删除用户？" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "确认永久删除" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("有历史记录，只能停用账号");
});
