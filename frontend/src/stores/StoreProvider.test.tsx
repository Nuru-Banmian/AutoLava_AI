import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  const { selected, select } = useStore();
  return (
    <>
      <span>selected:{selected?.name ?? "未选择"}</span>
      <button onClick={() => select(2)}>select Roma</button>
    </>
  );
}

function renderProvider(userId: number) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StoreProvider userId={userId}>
        <Probe />
      </StoreProvider>
    </QueryClientProvider>,
  );
}

describe("StoreProvider selection persistence", () => {
  it("restores a permitted store for the same user", async () => {
    server.use(
      http.get("/api/stores/accessible", () =>
        HttpResponse.json([
          { id: 1, name: "Berlin", timezone: "Europe/Berlin" },
          { id: 2, name: "Roma", timezone: "Europe/Rome" },
        ]),
      ),
    );

    const firstSession = renderProvider(1);
    expect(await screen.findByText("selected:Berlin")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "select Roma" }));
    expect(await screen.findByText("selected:Roma")).toBeInTheDocument();
    firstSession.unmount();

    renderProvider(1);

    expect(await screen.findByText("selected:Roma")).toBeInTheDocument();
  });

  it("does not inherit a shared-store selection from another user", async () => {
    server.use(
      http.get("/api/stores/accessible", () =>
        HttpResponse.json([
          { id: 1, name: "Berlin", timezone: "Europe/Berlin" },
          { id: 2, name: "Roma", timezone: "Europe/Rome" },
        ]),
      ),
    );

    const firstUser = renderProvider(1);
    expect(await screen.findByText("selected:Berlin")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "select Roma" }));
    expect(await screen.findByText("selected:Roma")).toBeInTheDocument();
    firstUser.unmount();

    renderProvider(2);

    expect(await screen.findByText("selected:Berlin")).toBeInTheDocument();
  });

  it("replaces a revoked store with the first accessible store", async () => {
    localStorage.setItem(STORE_SELECTION_KEY, JSON.stringify({ userId: 1, storeId: 99 }));
    server.use(
      http.get("/api/stores/accessible", () =>
        HttpResponse.json([
          { id: 1, name: "Berlin", timezone: "Europe/Berlin" },
          { id: 2, name: "Roma", timezone: "Europe/Rome" },
        ]),
      ),
    );

    renderProvider(1);

    expect(await screen.findByText("selected:Berlin")).toBeInTheDocument();
    expect(localStorage.getItem(STORE_SELECTION_KEY)).toBe(JSON.stringify({ userId: 1, storeId: 1 }));
  });

  it("clears a saved store when no stores are accessible", async () => {
    localStorage.setItem(STORE_SELECTION_KEY, JSON.stringify({ userId: 1, storeId: 2 }));
    server.use(http.get("/api/stores/accessible", () => HttpResponse.json([])));

    renderProvider(1);

    expect(await screen.findByText("selected:未选择")).toBeInTheDocument();
    await waitFor(() => expect(localStorage.getItem(STORE_SELECTION_KEY)).toBeNull());
  });

  it("ignores an unscoped legacy store id", async () => {
    localStorage.setItem(STORE_SELECTION_KEY, "2");
    server.use(
      http.get("/api/stores/accessible", () =>
        HttpResponse.json([
          { id: 1, name: "Berlin", timezone: "Europe/Berlin" },
          { id: 2, name: "Roma", timezone: "Europe/Rome" },
        ]),
      ),
    );

    renderProvider(1);

    expect(await screen.findByText("selected:Berlin")).toBeInTheDocument();
  });
});
