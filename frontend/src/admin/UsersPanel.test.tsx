import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";

import { UsersPanel } from "@/admin/UsersPanel";
import type { AdminUser } from "@/api/types";
import { UnsavedChangesProvider } from "@/navigation/UnsavedChanges";

const authState = vi.hoisted(() => ({
  user: { id: 1, username: "Nuru_Banmian", role: "admin" as const, is_owner: true },
}));

vi.mock("@/auth/AuthProvider", () => ({ useAuth: () => authState }));

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  authState.user = { id: 1, username: "Nuru_Banmian", role: "admin", is_owner: true };
});
afterAll(() => server.close());

const roma = {
  id: 9,
  name: "Roma",
  address: "Via Roma",
  latitude: "41.9",
  longitude: "12.5",
  timezone: "Europe/Rome",
  is_active: true,
};
const maria = {
  id: 2,
  username: "maria",
  role: "user" as const,
  is_active: true,
  store_ids: [9],
};
const operator = {
  id: 3,
  username: "operator",
  role: "user" as const,
  is_active: true,
  store_ids: [],
};

function mockUsers(
  items: AdminUser[],
  captureCreate?: (request: Request) => Promise<void>,
) {
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json(items)),
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.post("/api/admin/users", async ({ request }) => {
      await captureCreate?.(request);
      return HttpResponse.json({
        id: 10,
        username: "operator",
        role: "user",
        is_active: true,
        store_ids: [9],
      }, { status: 201 });
    }),
  );
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false },
    mutations: { retry: false },
  } });
  return render(
    <QueryClientProvider client={client}>
      <UnsavedChangesProvider><UsersPanel /></UnsavedChangesProvider>
    </QueryClientProvider>,
  );
}

it("selects a user into one editor and removes duplicate management surfaces", async () => {
  mockUsers([maria]);
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
