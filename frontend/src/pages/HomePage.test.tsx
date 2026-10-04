import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";
import { useAuth } from "@/auth/AuthProvider";
import { HomePage } from "@/pages/HomePage";
import { StoreProvider, useStore } from "@/stores/StoreProvider";
vi.mock("@/auth/AuthProvider", () => ({ useAuth: vi.fn() }));
function StoreControls() { const { select } = useStore(); return <><button onClick={() => select(1)}>choose1</button><button onClick={() => select(2)}>choose2</button></>; }
const server = setupServer(http.get("/api/ledger/:store/:date", () => HttpResponse.json({ detail: "Not found" }, { status: 404 }))); beforeAll(() => server.listen({ onUnhandledRequest: "error" })); afterEach(() => { server.resetHandlers(); vi.useRealTimers(); }); afterAll(() => server.close());
const emptyFields = { revenue: null, weather: null, weekday: null, temperature_max: null, temperature_min: null, precipitation: null, hint: null };

it("offers a read-only view of an archived store's recorded daily ledger", async () => {
  server.use(
    http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Archived", timezone: "Europe/Berlin", is_active: false }])),
    http.get("/api/dashboard/1", () => HttpResponse.json([])),
    http.get("/api/ledger/1/:date", () => HttpResponse.json({ is_open: "营业", daily_revenue: 73 })),
  );
  render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><StoreProvider><HomePage /></StoreProvider></QueryClientProvider></MemoryRouter>);
  expect(await screen.findByText("今日已记录")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "查看今日台账" })).toHaveAttribute("href", "/database");
  expect(screen.queryByRole("link", { name: "修改今日台账" })).not.toBeInTheDocument();
});

it("uses the store-local today's daily ledger instead of a stale recorded briefing", async () => {
  vi.mocked(useAuth).mockReturnValue({ user: { id: 2, username: "user", role: "user", is_owner: false } } as ReturnType<typeof useAuth>);
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-07-15T00:30:00Z"));
  server.use(
    http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "West", timezone: "America/Los_Angeles" }])),
    http.get("/api/dashboard/1", () => HttpResponse.json([{ card_type: "today", state: "recorded", ...emptyFields, revenue: 999, generated_at: "2026-07-13T00:00:00Z" }])),
    http.get("/api/ledger/1/2026-07-14", () => HttpResponse.json({ detail: "Not found" }, { status: 404 })),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><StoreProvider><HomePage /></StoreProvider></QueryClientProvider>);
  const today = await screen.findByRole("region", { name: "今日状态" });
  expect(await within(today).findByText("今日尚未记录")).toBeInTheDocument();
  expect(within(today).getByText("2026-07-14")).toBeInTheDocument();
  expect(within(today).getByText("营业状态：待记录")).toBeInTheDocument();
  expect(within(today).getByRole("link", { name: "立即记账" })).toHaveAttribute("href", "/ledger?date=2026-07-14");
  expect(screen.queryByText("€999")).not.toBeInTheDocument();
});

it("renders the approved missing-yesterday action without assigning ledger state to tomorrow", async () => {
  vi.mocked(useAuth).mockReturnValue({ user: { id: 2, username: "user", role: "user", is_owner: false } } as ReturnType<typeof useAuth>);
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-07-15T12:00:00"));
  server.use(
    http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
    http.get("/api/dashboard/1", () => HttpResponse.json([
      { card_type: "yesterday", state: "missing", ...emptyFields, generated_at: "2026-07-15T04:00:00" },
      { card_type: "today", state: "recorded", ...emptyFields, revenue: 120, weather: "晴", generated_at: "2026-07-15T04:00:00" },
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
    vi.mocked(useAuth).mockReturnValue({ user: { id: 2, username: "user", role: "user", is_owner: false } } as ReturnType<typeof useAuth>);
    server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])), http.get("/api/dashboard/1", () => HttpResponse.json([{ card_type: "yesterday", state: "recorded", ...emptyFields, revenue: 88, generated_at: "2026-07-14T00:00:00" }])), http.post("/api/dashboard/1/refresh", () => HttpResponse.json({ detail: "请等待五分钟后再刷新" }, { status: 429 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><StoreProvider><HomePage /></StoreProvider></QueryClientProvider>);
  expect(await screen.findByText("€88")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "刷新简报" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("请等待五分钟"); expect(screen.getByText("€88")).toBeInTheDocument();
});

it.each([["营业", 0], ["休息", 0], ["提前休息", 73]])("reads a recorded %s daily ledger even when its amount is zero", async (status, amount) => {
  server.use(
    http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
    http.get("/api/dashboard/1", () => HttpResponse.json([])),
    http.get("/api/ledger/1/:date", () => HttpResponse.json({ is_open: status, daily_revenue: amount })),
  );
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><StoreProvider><HomePage /></StoreProvider></QueryClientProvider>);
  const today = await screen.findByRole("region", { name: "今日状态" });
  expect(await within(today).findByText("今日已记录")).toBeInTheDocument();
  expect(within(today).getByText(`营业状态：${status}`)).toBeInTheDocument();
  expect(within(today).getByText(`总营业额 €${amount}`)).toBeInTheDocument();
  expect(within(today).getByRole("link", { name: "修改今日台账" })).toBeInTheDocument();
});

it("distinguishes exhausted request failures from missing daily ledgers and recovers by retry", async () => {
  let failing = true;
  let failures = 0;
  server.use(
    http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
    http.get("/api/dashboard/1", () => HttpResponse.json([])),
    http.get("/api/ledger/1/:date", () => { if (failing) failures++; return failing ? HttpResponse.json({ detail: "Unavailable" }, { status: 500 }) : HttpResponse.json({ detail: "Not found" }, { status: 404 }); }),
  );
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: 2, retryDelay: 0 } } })}><StoreProvider><HomePage /></StoreProvider></QueryClientProvider>);
  const today = await screen.findByRole("region", { name: "今日状态" });
  expect(await within(today).findByRole("alert")).toHaveTextContent("无法确认是否已记录");
  expect(failures).toBe(3);
  expect(within(today).queryByText("今日尚未记录")).not.toBeInTheDocument();
  failing = false;
  fireEvent.click(within(today).getByRole("button", { name: "重试今日状态" }));
  expect(await within(today).findByText("今日尚未记录")).toBeInTheDocument();
});

it("keeps the current store's state after a late daily ledger response", async () => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let started = false;
  let finished = false;
  server.use(
    http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "One", timezone: "Europe/Berlin" }, { id: 2, name: "Two", timezone: "America/Los_Angeles" }])),
    http.get("/api/dashboard/:store", () => HttpResponse.json([])),
    http.get("/api/ledger/1/:date", async () => { started = true; await gate; finished = true; return HttpResponse.json({ is_open: "提前休息", daily_revenue: 999 }); }),
  );
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><StoreProvider><StoreControls /><HomePage /></StoreProvider></QueryClientProvider>);
  await waitFor(() => expect(started).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: "choose2" }));
  expect(await screen.findByText("今日尚未记录")).toBeInTheDocument();
  await act(async () => { release(); await gate; });
  await waitFor(() => expect(finished).toBe(true));
  expect(screen.getByText("今日尚未记录")).toBeInTheDocument();
  expect(screen.queryByText(/€999/)).not.toBeInTheDocument();
});
it("clears a refresh error when the selected store changes", async () => {
  vi.mocked(useAuth).mockReturnValue({ user: { id: 2, username: "user", role: "user", is_owner: false } } as ReturnType<typeof useAuth>);
  server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "One", timezone: "Europe/Berlin" }, { id: 2, name: "Two", timezone: "Europe/Berlin" }])), http.get("/api/dashboard/:store", () => HttpResponse.json([])), http.post("/api/dashboard/1/refresh", () => HttpResponse.json({ detail: "wait" }, { status: 429 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); render(<QueryClientProvider client={client}><StoreProvider><StoreControls /><HomePage /></StoreProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "choose1" })); fireEvent.click(await screen.findByRole("button", { name: "刷新简报" })); expect(await screen.findByRole("alert")).toHaveTextContent("wait");
  fireEvent.click(screen.getByRole("button", { name: "choose2" })); await screen.findByRole("button", { name: "刷新简报" }); expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
