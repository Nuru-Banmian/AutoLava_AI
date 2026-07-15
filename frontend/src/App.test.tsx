import { render, screen } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import App, { Application } from "./App";
import { createAppRouter } from "./router";

const server = setupServer(
  http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "admin", role: "admin" })),
  http.get("/api/stores/accessible", () => HttpResponse.json([])),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderApplication(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<Application queryClient={queryClient} router={createAppRouter([path])} />);
}

describe("App", () => {
  it("loads the shared application shell", async () => {
    renderApplication("/");
    expect(await screen.findByText("AutoLava AI")).toBeInTheDocument();
    expect(document.documentElement).toBeTruthy();
  });

  it("renders the login page for an unauthenticated browser session", async () => {
    server.use(http.get("/api/auth/me", () => HttpResponse.json({ detail: "Authentication required" }, { status: 401 })));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
  });
});
