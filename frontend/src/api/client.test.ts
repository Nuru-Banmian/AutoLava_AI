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

  it("preserves a Headers instance and does not add content type to a bodyless request", async () => {
    let authorization: string | null = null;
    let contentType: string | null = null;
    server.use(http.get("/api/headers", ({ request }) => {
      authorization = request.headers.get("authorization");
      contentType = request.headers.get("content-type");
      return HttpResponse.json({ ok: true });
    }));

    await api("/headers", { headers: new Headers({ Authorization: "Bearer secret" }) });

    expect(authorization).toBe("Bearer secret");
    expect(contentType).toBeNull();
  });

  it("preserves tuple headers and an explicit content type for a request body", async () => {
    let authorization: string | null = null;
    let contentType: string | null = null;
    server.use(http.post("/api/headers", ({ request }) => {
      authorization = request.headers.get("authorization");
      contentType = request.headers.get("content-type");
      return HttpResponse.json({ ok: true });
    }));
    const headers: [string, string][] = [
      ["Authorization", "Bearer tuple"],
      ["Content-Type", "application/merge-patch+json"],
    ];

    await api("/headers", { method: "POST", headers, body: "{}" });

    expect(authorization).toBe("Bearer tuple");
    expect(contentType).toBe("application/merge-patch+json");
  });
});
