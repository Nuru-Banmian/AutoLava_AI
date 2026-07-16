import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";

import { StoreLocationPicker } from "@/components/StoreLocationPicker";
import type { MapAdapter, MapLocation } from "@/maps/types";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { server.resetHandlers(); vi.restoreAllMocks(); });
afterAll(() => server.close());

const initial: MapLocation = { label: "Roma Centro", latitude: 41.9, longitude: 12.5, timezone: "Europe/Rome" };

function adapterHarness() {
  let move: ((point: { latitude: number; longitude: number }) => void) | undefined;
  const cleanup = vi.fn();
  const adapter: MapAdapter = { mount: vi.fn((_node, _value, onChange) => { move = onChange; return cleanup; }) };
  return { adapter, cleanup, move: (point: { latitude: number; longitude: number }) => move?.(point) };
}

it("mounts the injected adapter and cleans it up when closed", async () => {
  const map = adapterHarness();
  render(<StoreLocationPicker adapter={map.adapter} value={initial} onConfirm={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "修改地图位置" }));
  await waitFor(() => expect(map.adapter.mount).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  await waitFor(() => expect(map.cleanup).toHaveBeenCalledOnce());
});

it("searches through the backend and confirms only a complete location", async () => {
  const onConfirm = vi.fn();
  server.use(http.get("/api/admin/stores/geocode", () => HttpResponse.json([
    { name: "Milano", country: "Italia", latitude: 45.46, longitude: 9.19, timezone: "Europe/Rome" },
  ])));
  render(<StoreLocationPicker adapter={adapterHarness().adapter} value={null} onConfirm={onConfirm} />);
  fireEvent.click(screen.getByRole("button", { name: "打开地图选择" }));
  fireEvent.change(screen.getByLabelText("搜索城市、区域或地点"), { target: { value: "Milano" } });
  fireEvent.submit(screen.getByRole("search"));
  fireEvent.click(await screen.findByRole("button", { name: /Milano.*Italia/ }));
  fireEvent.click(screen.getByRole("button", { name: "确认位置" }));
  expect(onConfirm).toHaveBeenCalledWith({ label: "Milano, Italia", latitude: 45.46, longitude: 9.19, timezone: "Europe/Rome" });
});

it("shows a Chinese fallback when browser location is denied", () => {
  Object.defineProperty(navigator, "geolocation", { configurable: true, value: { getCurrentPosition: (_ok: unknown, fail: (error: unknown) => void) => fail(new Error("denied")) } });
  render(<StoreLocationPicker adapter={adapterHarness().adapter} value={null} onConfirm={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "打开地图选择" }));
  fireEvent.click(screen.getByRole("button", { name: "使用当前位置" }));
  expect(screen.getByRole("alert")).toHaveTextContent("无法获取当前位置，你仍然可以搜索地点");
});

it("ignores a late timezone response after a newer map move", async () => {
  const map = adapterHarness();
  let resolveFirst!: (value: Response) => void;
  vi.spyOn(globalThis, "fetch")
    .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ timezone: "Europe/Rome" }), { status: 200, headers: { "Content-Type": "application/json" } }));
  render(<StoreLocationPicker adapter={map.adapter} value={initial} onConfirm={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "修改地图位置" }));
  await waitFor(() => expect(map.adapter.mount).toHaveBeenCalledOnce());
  map.move({ latitude: 10, longitude: 10 });
  map.move({ latitude: 45, longitude: 9 });
  await screen.findByText("地图选点 · Europe/Rome");
  resolveFirst(new Response(JSON.stringify({ timezone: "Asia/Shanghai" }), { status: 200, headers: { "Content-Type": "application/json" } }));
  await waitFor(() => expect(screen.queryByText(/Asia\/Shanghai/)).not.toBeInTheDocument());
});
