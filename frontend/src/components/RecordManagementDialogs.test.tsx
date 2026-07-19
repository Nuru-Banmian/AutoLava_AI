import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { RecordSnapshot } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { RecordManagementDialogs } from "@/components/RecordManagementDialogs";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: vi.fn() }));

const server = setupServer();
const record = {
  id: 4, store_id: 1, date: "2026-07-14", daily_revenue: 100, income_mode: "composed",
  wash_count: 8, is_open: "营业", weather: "晴", weather_auto: "晴", weather_code: 1,
  temperature_max: "20.0", temperature_min: "10.0", precipitation: "0.0",
  activity: null, weather_edited: false, scanned: false, created_by: 1, updated_by: 1,
  created_at: "", updated_at: "", items: [],
} satisfies RecordSnapshot;

function renderDialogs(recordValue: RecordSnapshot | null = record) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  for (const key of [
    ["ledger", "record", 1, "2026-07-14"],
    ["ledgerMonth", 1, "2026-07"],
    ["ledger", "recent", 1, 7],
    ["database", "records", 1, "query"],
    ["charts", 1, "query"],
    ["dashboard", 1],
  ]) client.setQueryData(key, true);
  render(<QueryClientProvider client={client}><RecordManagementDialogs storeId={1} record={recordValue} open onOpenChange={vi.fn()} onCompleted={vi.fn()} /></QueryClientProvider>);
  return client;
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { server.resetHandlers(); vi.restoreAllMocks(); });
afterAll(() => server.close());

describe("RecordManagementDialogs", () => {
  it("permanently deletes without version, history, or rollback requests and invalidates dependants", async () => {
    const requests: string[] = [];
    server.use(
      http.all("/api/*", ({ request }) => {
        requests.push(request.url);
        if (request.method === "DELETE") return new HttpResponse(null, { status: 204 });
        return HttpResponse.json({ detail: "unexpected request" }, { status: 500 });
      }),
    );
    vi.mocked(useAuth).mockReturnValue({ user: { id: 1, username: "admin", role: "admin", is_owner: false } } as ReturnType<typeof useAuth>);
    const client = renderDialogs();

    fireEvent.click(screen.getByRole("button", { name: "永久删除这天记录" }));
    expect(screen.getByText("删除后无法恢复。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认永久删除" }));

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0]).toMatch(/\/api\/ledger\/1\/2026-07-14$/);
    expect(requests.some((request) => request.includes("/history") || request.includes("/rollback"))).toBe(false);
    await waitFor(() => {
      for (const key of [
        ["ledger", "record", 1, "2026-07-14"],
        ["ledgerMonth", 1, "2026-07"],
        ["ledger", "recent", 1, 7],
        ["database", "records", 1, "query"],
        ["charts", 1, "query"],
        ["dashboard", 1],
      ]) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    });
  });

  it("shows no destructive controls to non-admin users", () => {
    vi.mocked(useAuth).mockReturnValue({ user: { id: 2, username: "user", role: "user", is_owner: false } } as ReturnType<typeof useAuth>);
    renderDialogs();

    expect(screen.queryByRole("button", { name: "永久删除这天记录" })).not.toBeInTheDocument();
    expect(screen.queryByText(/历史|回滚/)).not.toBeInTheDocument();
  });

  it("does not offer deletion when there is no saved record", () => {
    vi.mocked(useAuth).mockReturnValue({ user: { id: 1, username: "admin", role: "admin", is_owner: false } } as ReturnType<typeof useAuth>);
    renderDialogs(null);

    expect(screen.queryByRole("button", { name: "永久删除这天记录" })).not.toBeInTheDocument();
  });
});
