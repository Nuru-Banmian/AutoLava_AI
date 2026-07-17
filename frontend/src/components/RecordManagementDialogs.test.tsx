import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { AuditEntry, RecordSnapshot } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { RecordManagementDialogs } from "@/components/RecordManagementDialogs";
import { invalidateUserData } from "@/lib/user-api";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: vi.fn() }));
vi.mock("@/lib/user-api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/user-api")>(),
  invalidateUserData: vi.fn(),
}));

const server = setupServer();
const record: RecordSnapshot = {
  id: 4, store_id: 1, date: "2026-07-14", daily_revenue: "100.00", income_mode: "composed", income_config_version_id: 3, row_version: 1,
  wash_count: 8, is_open: "营业", weather: "晴", weather_auto: "晴", weather_code: 1, temperature_max: "20.0", temperature_min: "10.0", precipitation: "0.0",
  activity: null, weather_edited: false, scanned: false, created_by: 1, updated_by: 1, created_at: "", updated_at: "", items: [],
};
const audit: AuditEntry = { id: 9, record_id: 4, record_date: "2026-07-14", operation_type: "update", operation_source: "manual", operator_user_id: 1, operator_username: "admin", before: record, after: record, description: "修改", requires_approval: false, approved: true, rollbackable: true, created_at: "" };

function renderDialogs(props: Partial<React.ComponentProps<typeof RecordManagementDialogs>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidatedRoots: string[] = [];
  const invalidateQueries = client.invalidateQueries.bind(client);
  vi.spyOn(client, "invalidateQueries").mockImplementation(async (filters) => {
    const root = filters?.queryKey?.[0];
    if (typeof root === "string") invalidatedRoots.push(root);
    return invalidateQueries(filters);
  });
  vi.mocked(invalidateUserData).mockImplementation(async () => {
    invalidatedRoots.push("ledger", "database", "charts", "dashboard");
  });
  render(<QueryClientProvider client={client}><RecordManagementDialogs storeId={1} record={record} targetDate="2026-07-14" open onOpenChange={vi.fn()} onCompleted={vi.fn()} {...props} /></QueryClientProvider>);
  return { invalidatedRoots };
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { server.resetHandlers(); vi.restoreAllMocks(); });
afterAll(() => server.close());

describe("RecordManagementDialogs", () => {
  it("deletes with the displayed version, exposes rollback, and invalidates dependent data", async () => {
    let deleteRequest = "";
    server.use(
      http.get("/api/database/1/history", () => HttpResponse.json({ items: [audit], total: 1, page: 1, page_size: 20 })),
      http.delete("/api/ledger/1/2026-07-14", ({ request }) => { deleteRequest = request.url; return new HttpResponse(null, { status: 204 }); }),
    );
    vi.mocked(useAuth).mockReturnValue({ user: { id: 1, username: "admin", role: "admin", is_owner: false } } as ReturnType<typeof useAuth>);
    const { invalidatedRoots } = renderDialogs();

    fireEvent.click(await screen.findByRole("button", { name: "删除这天记录" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(deleteRequest).not.toBe(""));
    expect(new URL(deleteRequest).search).toBe("?expected_version=1");
    expect(await screen.findByRole("button", { name: "回滚 #9" })).toBeInTheDocument();
    await waitFor(() => expect(invalidatedRoots).toEqual(expect.arrayContaining(["ledger", "database", "charts", "dashboard"])));
  });

  it("shows a reloadable stale-delete message", async () => {
    server.use(
      http.get("/api/database/1/history", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })),
      http.delete("/api/ledger/1/2026-07-14", () => HttpResponse.json({ detail: "Record changed" }, { status: 409 })),
    );
    vi.mocked(useAuth).mockReturnValue({ user: { id: 1, username: "admin", role: "admin", is_owner: false } } as ReturnType<typeof useAuth>);
    renderDialogs();

    fireEvent.click(await screen.findByRole("button", { name: "删除这天记录" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("数据已经发生变化，请刷新后重试");
    expect(screen.getByRole("button", { name: "重新加载记录" })).toBeInTheDocument();
  });

  it("does not expose history, deletion, or rollback to non-admin users", () => {
    vi.mocked(useAuth).mockReturnValue({ user: { id: 2, username: "user", role: "user", is_owner: false } } as ReturnType<typeof useAuth>);
    renderDialogs();

    expect(screen.queryByRole("button", { name: "删除这天记录" })).not.toBeInTheDocument();
    expect(screen.queryByText("修改历史")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /回滚/ })).not.toBeInTheDocument();
  });
});
