import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { STORE_SELECTION_KEY, StoreProvider, useStore } from "@/stores/StoreProvider";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  localStorage.clear();
  server.resetHandlers();
});
afterAll(() => server.close());

function Probe() {
  const { selected } = useStore();
  return <span>{selected?.name ?? "未选择"}</span>;
}

function renderProvider() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StoreProvider>
        <Probe />
      </StoreProvider>
    </QueryClientProvider>,
  );
}

describe("StoreProvider selection persistence", () => {
  it("restores a permitted store", async () => {
    localStorage.setItem("autolava:selected-store", "2");
    server.use(
      http.get("/api/stores/accessible", () =>
        HttpResponse.json([
          { id: 1, name: "Berlin", timezone: "Europe/Berlin" },
          { id: 2, name: "Roma", timezone: "Europe/Rome" },
        ]),
      ),
    );

    renderProvider();

    expect(await screen.findByText("Roma")).toBeInTheDocument();
  });

  it("replaces a revoked store with the first accessible store", async () => {
    localStorage.setItem("autolava:selected-store", "99");
    server.use(
      http.get("/api/stores/accessible", () =>
        HttpResponse.json([
          { id: 1, name: "Berlin", timezone: "Europe/Berlin" },
          { id: 2, name: "Roma", timezone: "Europe/Rome" },
        ]),
      ),
    );

    renderProvider();

    expect(await screen.findByText("Berlin")).toBeInTheDocument();
    expect(localStorage.getItem("autolava:selected-store")).toBe("1");
  });

  it("clears a saved store when no stores are accessible", async () => {
    localStorage.setItem("autolava:selected-store", "2");
    server.use(http.get("/api/stores/accessible", () => HttpResponse.json([])));

    renderProvider();

    expect(await screen.findByText("未选择")).toBeInTheDocument();
    await waitFor(() => expect(localStorage.getItem(STORE_SELECTION_KEY)).toBeNull());
  });
});
