import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { api } from "@/api/client";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("api", () => {
  it("prefixes API paths, includes credentials, sends JSON, and handles 204", async () => {
    let credentials: RequestCredentials | undefined;
    let body: unknown;
    server.use(http.post("/api/example", async ({ request }) => {
      credentials = request.credentials;
      body = await request.json();
      return new HttpResponse(null, { status: 204 });
    }));

    const result = await api<void>("example", { method: "POST", body: JSON.stringify({ ok: true }) });

    expect(result).toBeUndefined();
    expect(credentials).toBe("include");
    expect(body).toEqual({ ok: true });
  });

  it("surfaces FastAPI 422 validation messages", async () => {
    server.use(http.get("/api/invalid", () => HttpResponse.json({ detail: [
      { loc: ["body", "name"], msg: "Field required", type: "missing" },
      { loc: ["body", "password"], msg: "Too short", type: "value_error" },
    ] }, { status: 422 })));

    await expect(api("/invalid")).rejects.toMatchObject({
      status: 422,
      detail: "Field required; Too short",
    });
  });

  it("uses a readable plain-text server error instead of throwing a JSON parse error", async () => {
    server.use(http.get("/api/unavailable", () => new HttpResponse("Gateway unavailable", {
      status: 502,
      headers: { "Content-Type": "text/plain" },
    })));

    await expect(api("/unavailable")).rejects.toMatchObject({
      status: 502,
      detail: "Gateway unavailable",
    });
  });
});
