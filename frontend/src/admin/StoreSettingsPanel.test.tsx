import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";

import { StoreSettingsPanel } from "@/admin/StoreSettingsPanel";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { server.resetHandlers(); vi.restoreAllMocks(); });
afterAll(() => server.close());

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><StoreSettingsPanel /></QueryClientProvider>);
}

const roma = { id: 9, name: "Roma", address: "Roma Centro", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true };

it("keeps the current-store selector and new-store action together in the header", async () => {
  server.use(http.get("/api/admin/stores", () => HttpResponse.json([roma])));
  renderPanel();

  const header = await screen.findByRole("banner", { name: "门店设置操作" });
  expect(within(header).getByLabelText("当前门店")).toBeInTheDocument();
  expect(within(header).getByRole("button", { name: "新建门店" })).toBeInTheDocument();
  expect(screen.queryByLabelText("门店名称")).not.toBeInTheDocument();
  fireEvent.click(within(header).getByRole("button", { name: "新建门店" }));
  expect(screen.getByLabelText("门店名称")).toBeInTheDocument();
  expect(screen.queryByLabelText("纬度")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("经度")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "打开地图选择" })).toBeInTheDocument();
  fireEvent.click(within(header).getByRole("button", { name: "取消新建" }));
  expect(screen.queryByLabelText("门店名称")).not.toBeInTheDocument();
  await within(header).findByRole("option", { name: "Roma" });
  expect(await screen.findByLabelText("门店名称 Roma")).toBeInTheDocument();
  expect(screen.getByText("Roma Centro")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "修改地图位置" })).toBeInTheDocument();
});

it("puts deactivate and permanent delete in a confirmed danger area", async () => {
  let deleted = false;
  vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  server.use(
    http.get("/api/admin/stores", () => HttpResponse.json(deleted ? [] : [roma])),
    http.delete("/api/admin/stores/9", () => { deleted = true; return new HttpResponse(null, { status: 204 }); }),
  );
  renderPanel();
  const danger = await screen.findByRole("region", { name: "危险操作" });

  fireEvent.click(within(danger).getByRole("button", { name: "永久删除门店 Roma" }));
  expect(deleted).toBe(false);
  fireEvent.click(within(danger).getByRole("button", { name: "永久删除门店 Roma" }));

  await waitFor(() => expect(screen.queryByText("Roma Centro")).not.toBeInTheDocument());
  expect(window.confirm).toHaveBeenCalledTimes(2);
});

it("explains that a referenced store must be deactivated when deletion returns 409", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  server.use(
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.delete("/api/admin/stores/9", () => HttpResponse.json({ detail: "该门店已有业务或历史记录，请停用门店而不是删除" }, { status: 409 })),
  );
  renderPanel();

  fireEvent.click(await screen.findByRole("button", { name: "永久删除门店 Roma" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("已有经营或历史记录，只能停用门店");
});

it("does not carry a delete error to another selected store", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const milano = { ...roma, id: 10, name: "Milano", address: "Milano Centro" };
  server.use(
    http.get("/api/admin/stores", () => HttpResponse.json([roma, milano])),
    http.delete("/api/admin/stores/9", () => HttpResponse.json({ detail: "该门店已有业务或历史记录，请停用门店而不是删除" }, { status: 409 })),
  );
  renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: "永久删除门店 Roma" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("当前门店"), { target: { value: "10" } });

  expect(await screen.findByLabelText("门店名称 Milano")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
