import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it } from "vitest";
import { HomePage } from "@/pages/HomePage";
import { StoreProvider } from "@/stores/StoreProvider";
const server = setupServer(); beforeAll(() => server.listen({ onUnhandledRequest: "error" })); afterEach(() => server.resetHandlers()); afterAll(() => server.close());
it("keeps cached cards visible and shows the 429 refresh detail", async () => {
  server.use(http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])), http.get("/api/dashboard/1", () => HttpResponse.json([{ card_type: "today", content: "旧简报", generated_at: "2026-07-14T00:00:00" }])), http.post("/api/dashboard/1/refresh", () => HttpResponse.json({ detail: "Please wait five minutes before refreshing again" }, { status: 429 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><StoreProvider><HomePage /></StoreProvider></QueryClientProvider>);
  expect(await screen.findByText("旧简报")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "刷新简报" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Please wait five minutes"); expect(screen.getByText("旧简报")).toBeInTheDocument();
});
