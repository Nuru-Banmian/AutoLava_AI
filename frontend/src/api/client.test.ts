import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ApiError, api, friendlyApiError } from "@/api/client";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("friendlyApiError", () => {
  it.each([
    [401, "Invalid credentials", "登录失败", "用户名或密码错误，请重新输入"],
    [403, "Inactive user", "登录失败", "这个账号已停用，请联系管理员"],
    [422, "Income configuration version does not match", "保存失败", "收入项目刚刚发生变化，页面已为你重新加载，请确认金额后再次保存"],
  ])("localizes the exact technical message %s %s", (status, detail, fallback, expected) => {
    expect(friendlyApiError(new ApiError(status, detail), fallback)).toBe(expected);
  });

  it.each([
    [403, "Administrator access required", "操作失败", "你没有权限执行这个操作"],
    [409, "Record changed; reload before saving", "保存失败", "数据已经发生变化，请刷新后重试"],
    [503, "Gateway unavailable", "加载失败", "服务器暂时不可用，请稍后重试"],
  ])("localizes generic ASCII status errors for %s", (status, detail, fallback, expected) => {
    expect(friendlyApiError(new ApiError(status, detail), fallback)).toBe(expected);
  });

  it("localizes an unmapped ASCII 401 response", () => {
    expect(friendlyApiError(new ApiError(401, "Authentication required"), "登录失败"))
      .toBe("登录状态已失效，请重新登录");
  });

  it.each([
    [404, "Store not found", "加载门店失败"],
    [422, "Field required", "保存失败"],
    [429, "Please wait five minutes before refreshing again", "刷新失败"],
  ])("uses the contextual fallback for an unmapped ASCII %s response", (status, detail, fallback) => {
    expect(friendlyApiError(new ApiError(status, detail), fallback)).toBe(fallback);
  });

  it("uses the contextual fallback for a network error", () => {
    expect(friendlyApiError(new TypeError("Failed to fetch"), "网络连接失败，请稍后重试"))
      .toBe("网络连接失败，请稍后重试");
  });

  it("uses the contextual fallback for an empty API detail", () => {
    expect(friendlyApiError(new ApiError(400, ""), "请求失败")).toBe("请求失败");
  });

  it("preserves a useful Chinese API detail", () => {
    expect(friendlyApiError(new ApiError(422, "金额不能为负数"), "保存失败"))
      .toBe("金额不能为负数");
  });
});

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
