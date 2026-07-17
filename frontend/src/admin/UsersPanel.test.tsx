import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type DefaultBodyType, HttpResponse, http } from "msw";
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
  expect(screen.queryByRole("button", { name: /操作历史/ })).not.toBeInTheDocument();
  expect(screen.queryByText("操作历史")).not.toBeInTheDocument();
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

it("requires explicit removal of inactive and unavailable memberships before saving", async () => {
  let patched: unknown;
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([{ ...maria, store_ids: [9, 99] }])),
    http.get("/api/admin/stores", () => HttpResponse.json([
      { ...roma, is_active: false },
      { ...roma, id: 10, name: "Milano" },
    ])),
    http.patch("/api/admin/users/2", async ({ request }) => {
      patched = await request.json();
      return HttpResponse.json({ ...maria, store_ids: [] });
    }),
  );
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));

  expect(screen.getByRole("alert")).toHaveTextContent("保存前请移除不可用的门店分配");
  expect(screen.getByText("Roma（已停用）")).toBeInTheDocument();
  expect(screen.getByText("门店 #99（不可用）")).toBeInTheDocument();
  const save = screen.getByRole("button", { name: "保存用户" });
  expect(save).toBeDisabled();
  fireEvent.submit(save.closest("form")!);
  expect(patched).toBeUndefined();

  await userEvent.click(screen.getByRole("button", { name: "移除 Roma（已停用）" }));
  await userEvent.click(screen.getByRole("button", { name: "移除 门店 #99（不可用）" }));
  expect(save).toBeEnabled();
  await userEvent.click(save);

  await waitFor(() => expect(patched).toEqual({
    role: "user",
    is_active: true,
    store_ids: [],
  }));
});

it("does not carry a failed edit error to another user", async () => {
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([maria, operator])),
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.patch("/api/admin/users/2", () => HttpResponse.json({ detail: "Maria edit rejected" }, { status: 409 })),
  );
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "replacement123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Maria edit rejected");

  await userEvent.click(screen.getByRole("button", { name: /operator/ }));
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));

  expect(screen.getByRole("heading", { name: "编辑 operator" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("resets the saved draft after a prior delete error", async () => {
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([maria])),
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.delete("/api/admin/users/2", () => HttpResponse.json({ detail: "该用户已有历史记录，不能永久删除；请停用账号" }, { status: 409 })),
    http.patch("/api/admin/users/2", async ({ request }) => HttpResponse.json({
      ...maria,
      ...(await request.json() as object),
    })),
  );
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  await userEvent.click(screen.getByRole("button", { name: "永久删除" }));
  await userEvent.click(screen.getByRole("button", { name: "确认删除" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("只能停用账号");

  const password = screen.getByLabelText("重置密码（可选）");
  await userEvent.type(password, "replacement123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));

  await waitFor(() => expect(password).toHaveValue(""));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("keeps the next user's draft after saving a different user", async () => {
  const alpha = { id: 4, username: "alpha-admin", role: "admin" as const, is_active: true, store_ids: [] };
  const beta = { id: 5, username: "beta", role: "user" as const, is_active: false, store_ids: [10] };
  const milano = { ...roma, id: 10, name: "Milano" };
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([alpha, beta])),
    http.get("/api/admin/stores", () => HttpResponse.json([roma, milano])),
    http.patch("/api/admin/users/4", () => HttpResponse.json(alpha)),
  );
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /alpha-admin/ }));
  const alphaPassword = screen.getByLabelText("重置密码（可选）");
  await userEvent.type(alphaPassword, "replacement123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));
  await waitFor(() => expect(alphaPassword).toHaveValue(""));

  await userEvent.click(screen.getByRole("button", { name: /beta/ }));

  expect(screen.getByRole("heading", { name: "编辑 beta" })).toBeInTheDocument();
  expect(screen.getByLabelText("角色")).toHaveValue("user");
  expect(screen.getByRole("checkbox", { name: "账号启用" })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Milano" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Roma" })).not.toBeChecked();
});

it("locks the submitted draft while a save is pending", async () => {
  let resolvePatch!: (response: HttpResponse<DefaultBodyType>) => void;
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([maria, operator])),
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.patch("/api/admin/users/2", () => new Promise<HttpResponse<DefaultBodyType>>((resolve) => { resolvePatch = resolve; })),
  );
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  const password = screen.getByLabelText("重置密码（可选）") as HTMLInputElement;
  const role = screen.getByLabelText("角色") as HTMLSelectElement;
  const active = screen.getByRole("checkbox", { name: "账号启用" }) as HTMLInputElement;
  const store = screen.getByRole("checkbox", { name: "Roma" }) as HTMLInputElement;
  await userEvent.type(password, "submitted123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));
  const saving = await screen.findByRole("button", { name: "保存中…" });

  const pendingState = {
    ariaBusy: saving.closest("form")?.getAttribute("aria-busy"),
    disabled: [password.disabled, role.disabled, active.disabled, store.disabled],
  };
  fireEvent.change(password, { target: { value: "not-sent-456" } });
  fireEvent.click(active);
  const attemptedState = { password: password.value, active: active.checked };
  await act(async () => resolvePatch(HttpResponse.json(maria)));
  await waitFor(() => expect(password).toHaveValue(""));

  expect(pendingState).toEqual({ ariaBusy: "true", disabled: [true, true, true, true] });
  expect(attemptedState).toEqual({ password: "submitted123", active: true });
  await userEvent.click(screen.getByRole("button", { name: /operator/ }));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});

it("ignores an older callback after a newer save for the same user", async () => {
  let requestCount = 0;
  let resolveFirst!: (response: HttpResponse<DefaultBodyType>) => void;
  let resolveSecond!: (response: HttpResponse<DefaultBodyType>) => void;
  let markFirstResponded!: () => void;
  const firstResponded = new Promise<void>((resolve) => { markFirstResponded = resolve; });
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json([maria, operator])),
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.patch("/api/admin/users/2", async () => {
      requestCount += 1;
      if (requestCount === 1) {
        const response = await new Promise<HttpResponse<DefaultBodyType>>((resolve) => { resolveFirst = resolve; });
        markFirstResponded();
        return response;
      }
      return new Promise<HttpResponse<DefaultBodyType>>((resolve) => { resolveSecond = resolve; });
    }),
  );
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /maria/ }));
  await userEvent.type(screen.getByLabelText("重置密码（可选）"), "first-pass-123");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));
  await waitFor(() => expect(resolveFirst).toBeDefined());
  await userEvent.click(screen.getByRole("button", { name: /operator/ }));
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
  await userEvent.click(screen.getByRole("button", { name: /maria/ }));
  const currentPassword = screen.getByLabelText("重置密码（可选）");
  await userEvent.type(currentPassword, "second-pass-456");
  await userEvent.click(screen.getByRole("button", { name: "保存用户" }));
  await waitFor(() => expect(resolveSecond).toBeDefined());

  await act(async () => resolveSecond(HttpResponse.json(maria)));
  await waitFor(() => expect(currentPassword).toHaveValue(""));
  await act(async () => {
    resolveFirst(HttpResponse.json({ detail: "stale failure" }, { status: 409 }));
    await firstResponded;
  });

  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(currentPassword).toHaveValue("");
  await userEvent.click(screen.getByRole("button", { name: /operator/ }));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});
