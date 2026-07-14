import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import App from "./App";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("App", () => {
  it("renders the login page for an unauthenticated browser session", async () => {
    server.use(http.get("/api/auth/me", () => HttpResponse.json({ detail: "Authentication required" }, { status: 401 })));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
  });
});
