import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { RecordSnapshot } from "@/api/types";
import { DeleteRecordDialog } from "@/components/DeleteRecordDialog";

const server = setupServer();
const record = {
  id: 4, store_id: 1, date: "2026-07-14", daily_revenue: 100, income_mode: "composed",
  wash_count: 8, is_open: "营业", weather: "晴", weather_auto: "晴", weather_code: 1,
  temperature_max: "20.0", temperature_min: "10.0", precipitation: "0.0",
  activity: null, weather_edited: false, scanned: false, created_by: 1, updated_by: 1,
  created_at: "", updated_at: "", items: [],
} satisfies RecordSnapshot;

function renderDialog(recordValue: RecordSnapshot | null = record) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  for (const key of [
    ["ledger", "record", 1, "2026-07-14"],
    ["ledgerMonth", 1, "2026-07"],
    ["ledger", "recent", 1, 7],
    ["database", "records", 1, "query"],
    ["charts", 1, "query"],
    ["dashboard", 1],
  ]) client.setQueryData(key, true);
  const onOpenChange = vi.fn();
  const onCompleted = vi.fn();
  render(<QueryClientProvider client={client}><DeleteRecordDialog storeId={1} record={recordValue} open onOpenChange={onOpenChange} onCompleted={onCompleted} /></QueryClientProvider>);
  return { client, onOpenChange, onCompleted };
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { server.resetHandlers(); vi.restoreAllMocks(); });
afterAll(() => server.close());

describe("DeleteRecordDialog", () => {
  it("permanently deletes without version, history, or rollback requests and invalidates dependants", async () => {
    const requests: string[] = [];
    server.use(
      http.all("/api/*", ({ request }) => {
        requests.push(request.url);
        if (request.method === "DELETE") return new HttpResponse(null, { status: 204 });
        return HttpResponse.json({ detail: "unexpected request" }, { status: 500 });
      }),
    );
    const { client, onOpenChange, onCompleted } = renderDialog();

    expect(screen.getByRole("alertdialog", { name: "确认永久删除记录？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认永久删除" }));

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0]).toMatch(/\/api\/ledger\/1\/2026-07-14$/);
    expect(requests.some((request) => request.includes("/history") || request.includes("/rollback"))).toBe(false);
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(onCompleted).toHaveBeenCalledOnce();
    expect(screen.getByRole("status", { hidden: true })).toHaveTextContent("删除成功");
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

  it("keeps the final confirmation open and retryable after a conflict", async () => {
    let requests = 0;
    server.use(http.delete("/api/ledger/1/2026-07-14", () => {
      requests += 1;
      return HttpResponse.json({ detail: "Record changed" }, { status: 409 });
    }));
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "确认永久删除" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("数据已经发生变化，请刷新后重试");
    expect(screen.getByRole("alertdialog", { name: "确认永久删除记录？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认永久删除" }));
    await waitFor(() => expect(requests).toBe(2));
  });

  it("renders no confirmation when there is no saved record", () => {
    renderDialog(null);

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
