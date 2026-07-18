import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";
import { HomePage } from "@/pages/HomePage";
import { StoreProvider, useStore } from "@/stores/StoreProvider";
function StoreControls() { const { select } = useStore(); return <><button onClick={() => select(1)}>choose1</button><button onClick={() => select(2)}>choose2</button></>; }
const server = setupServer(); beforeAll(() => server.listen({ onUnhandledRequest: "error" })); afterEach(() => { server.resetHandlers(); vi.useRealTimers(); }); afterAll(() => server.close());
const emptyFields = { revenue: null, weather: null, weekday: null, temperature_max: null, temperature_min: null, precipitation: null, hint: null };

it("renders the approved missing-yesterday action without assigning ledger state to tomorrow", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-07-15T12:00:00"));
  server.use(
    http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
    http.get("/api/dashboard/1", () => HttpResponse.json([
      { card_type: "yesterday", state: "missing", ...emptyFields, generated_at: "2026-07-15T04:00:00" },
      { card_type: "today", state: "recorded", ...emptyFields, revenue: "120.00", weather: "晴", generated_at: "2026-07-15T04:00:00" },
      { card_type: "tomorrow", state: "forecast", ...emptyFields, weather: "多云", weekday: "星期四", temperature_max: "25.00", temperature_min: "16.00", precipitation: "0.20", generated_at: "2026-07-15T04:00:00" },
    ])),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><StoreProvider><HomePage /></StoreProvider></QueryClientProvider>);

  expect(await screen.findByRole("heading", { name: "昨日" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "今日" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "明日" })).toBeInTheDocument();
  expect(screen.getByText("昨日尚未记录")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "补记昨日" })).toHaveAttribute("href", "/ledger?date=2026-07-14");
  expect(screen.getByRole("link", { name: "立即记账" })).toHaveAttribute("href", "/ledger?date=2026-07-15");
  expect(screen.queryByText(/明日.*尚未记账/)).not.toBeInTheDocument();
  expect(screen.getByText("多云")).toBeInTheDocument();
  expect(screen.getByText("16.00°C – 25.00°C")).toBeInTheDocument();
});
it("keeps cached cards visible and shows the 429 refresh detail", async () => {
  server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])), http.get("/api/dashboard/1", () => HttpResponse.json([{ card_type: "today", state: "recorded", ...emptyFields, revenue: "88.00", generated_at: "2026-07-14T00:00:00" }])), http.post("/api/dashboard/1/refresh", () => HttpResponse.json({ detail: "请等待五分钟后再刷新" }, { status: 429 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><StoreProvider><HomePage /></StoreProvider></QueryClientProvider>);
  expect(await screen.findByText("€88.00")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "刷新简报" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("请等待五分钟"); expect(screen.getByText("€88.00")).toBeInTheDocument();
});
it("clears a refresh error when the selected store changes", async () => {
  server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "One", timezone: "Europe/Berlin" }, { id: 2, name: "Two", timezone: "Europe/Berlin" }])), http.get("/api/dashboard/:store", () => HttpResponse.json([])), http.post("/api/dashboard/1/refresh", () => HttpResponse.json({ detail: "wait" }, { status: 429 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); render(<QueryClientProvider client={client}><StoreProvider><StoreControls /><HomePage /></StoreProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "choose1" })); fireEvent.click(await screen.findByRole("button", { name: "刷新简报" })); expect(await screen.findByRole("alert")).toHaveTextContent("wait");
  fireEvent.click(screen.getByRole("button", { name: "choose2" })); await screen.findByRole("button", { name: "刷新简报" }); expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
