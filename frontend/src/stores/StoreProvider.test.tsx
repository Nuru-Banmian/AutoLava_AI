import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { createMemoryRouter, Link, Outlet, RouterProvider } from "react-router-dom";

import { accessibleStoresKeyFor, STORE_SELECTION_KEY, StoreProvider, useStore } from "@/stores/StoreProvider";
import { UnsavedRouteGuard, useUnsavedChanges } from "@/navigation/UnsavedChanges";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  localStorage.clear();
  server.resetHandlers();
});
afterAll(() => server.close());

function Probe() {
  const { selected, select } = useStore();
  const { markDirty } = useUnsavedChanges();
  return (
    <>
      <span>selected:{selected?.name ?? "未选择"}</span>
      <input aria-label="账本输入" />
      <button onClick={() => markDirty(true)}>mark dirty</button>
      <button onClick={() => markDirty(false)}>mark clean</button>
      <button onClick={() => select(2)}>select Roma</button>
    </>
  );
}

function RouteStoreProbe() {
  const { selected } = useStore();
  const { markDirty } = useUnsavedChanges();
  return <><UnsavedRouteGuard /><span>route-store:{selected?.name ?? "未选择"}</span><button onClick={() => markDirty(true)}>route dirty</button><Link to="/next">route next</Link></>;
}

function providerTree(userId: number, client: QueryClient) {
  return (
    <QueryClientProvider client={client}>
      <StoreProvider userId={userId}>
        <Probe />
      </StoreProvider>
    </QueryClientProvider>
  );
}

function renderProvider(userId: number, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(providerTree(userId, client));
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

  it("does not use cached stores while a new user's stores are loading", async () => {
    let requests = 0;
    let secondRequestStarted = false;
    let resolveSecondRequest!: () => void;
    const secondRequest = new Promise<void>((resolve) => { resolveSecondRequest = resolve; });
    server.use(
      http.get("/api/stores/accessible", async () => {
        requests += 1;
        if (requests === 1) {
          return HttpResponse.json([
            { id: 1, name: "Berlin", timezone: "Europe/Berlin" },
            { id: 2, name: "Roma", timezone: "Europe/Rome" },
          ]);
        }
        secondRequestStarted = true;
        await secondRequest;
        return HttpResponse.json([
          { id: 3, name: "Madrid", timezone: "Europe/Madrid" },
          { id: 2, name: "Roma", timezone: "Europe/Rome" },
        ]);
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = renderProvider(1, client);
    expect(await screen.findByText("selected:Berlin")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "select Roma" }));
    expect(await screen.findByText("selected:Roma")).toBeInTheDocument();

    view.rerender(providerTree(2, client));

    await waitFor(() => expect(secondRequestStarted).toBe(true));
    expect(screen.getByText("selected:未选择")).toBeInTheDocument();
    expect(localStorage.getItem(STORE_SELECTION_KEY)).toBe(JSON.stringify({ userId: 1, storeId: 2 }));
    resolveSecondRequest();
    expect(await screen.findByText("selected:Madrid")).toBeInTheDocument();
    expect(localStorage.getItem(STORE_SELECTION_KEY)).toBe(JSON.stringify({ userId: 2, storeId: 3 }));
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

  it("clears a revoked store immediately even when input is dirty", async () => {
    server.use(http.get("/api/stores/accessible", () => HttpResponse.json([
      { id: 1, name: "Berlin", timezone: "Europe/Berlin" },
      { id: 2, name: "Roma", timezone: "Europe/Rome" },
    ])));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderProvider(1, client);
    expect(await screen.findByText("selected:Berlin")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "mark dirty" }));
    await act(async () => {
      client.setQueryData(accessibleStoresKeyFor(1), [{ id: 2, name: "Roma", timezone: "Europe/Rome" }]);
    });
    expect(await screen.findByText("selected:Roma")).toBeInTheDocument();
    expect(screen.queryByText("selected:Berlin")).not.toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(localStorage.getItem(STORE_SELECTION_KEY)).toBe(JSON.stringify({ userId: 1, storeId: 2 }));
  });

  it("clears dirty reconciliation immediately when the account changes", async () => {
    server.use(http.get("/api/stores/accessible", () => HttpResponse.json([
      { id: 1, name: "Berlin", timezone: "Europe/Berlin" },
      { id: 2, name: "Roma", timezone: "Europe/Rome" },
    ])));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = renderProvider(1, client);
    expect(await screen.findByText("selected:Berlin")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "mark dirty" }));
    client.setQueryData(accessibleStoresKeyFor(1), [
      { id: 2, name: "Roma", timezone: "Europe/Rome" },
    ]);
    expect(await screen.findByText("selected:Roma")).toBeInTheDocument();

    client.setQueryData(accessibleStoresKeyFor(2), [
      { id: 3, name: "Madrid", timezone: "Europe/Madrid" },
    ]);
    view.rerender(providerTree(2, client));

    expect(screen.queryByRole("alertdialog", { name: "放弃未保存的修改？" })).not.toBeInTheDocument();
    expect(await screen.findByText("selected:Madrid")).toBeInTheDocument();
    expect(screen.queryByText("selected:Berlin")).not.toBeInTheDocument();
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
