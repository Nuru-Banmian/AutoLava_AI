import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it } from "vitest";

import { UsersPanel } from "@/admin/UsersPanel";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><UsersPanel selectedStoreId={null} onSelectedStoreChange={() => undefined} /></QueryClientProvider>);
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
