import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it } from "vitest";
import { HomePage } from "@/pages/HomePage";
import { StoreProvider, useStore } from "@/stores/StoreProvider";
function StoreControls() { const { select } = useStore(); return <><button onClick={() => select(1)}>choose1</button><button onClick={() => select(2)}>choose2</button></>; }
const server = setupServer(); beforeAll(() => server.listen({ onUnhandledRequest: "error" })); afterEach(() => server.resetHandlers()); afterAll(() => server.close());
it("keeps cached cards visible and shows the 429 refresh detail", async () => {
  server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])), http.get("/api/dashboard/1", () => HttpResponse.json([{ card_type: "today", content: "旧简报", generated_at: "2026-07-14T00:00:00" }])), http.post("/api/dashboard/1/refresh", () => HttpResponse.json({ detail: "Please wait five minutes before refreshing again" }, { status: 429 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><StoreProvider><HomePage /></StoreProvider></QueryClientProvider>);
  expect(await screen.findByText("旧简报")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "刷新简报" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Please wait five minutes"); expect(screen.getByText("旧简报")).toBeInTheDocument();
});
it("clears a refresh error when the selected store changes", async () => {
  server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "One", timezone: "Europe/Berlin" }, { id: 2, name: "Two", timezone: "Europe/Berlin" }])), http.get("/api/dashboard/:store", () => HttpResponse.json([])), http.post("/api/dashboard/1/refresh", () => HttpResponse.json({ detail: "wait" }, { status: 429 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); render(<QueryClientProvider client={client}><StoreProvider><StoreControls /><HomePage /></StoreProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "choose1" })); fireEvent.click(await screen.findByRole("button", { name: "刷新简报" })); expect(await screen.findByRole("alert")).toHaveTextContent("wait");
  fireEvent.click(screen.getByRole("button", { name: "choose2" })); await screen.findByRole("button", { name: "刷新简报" }); expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
