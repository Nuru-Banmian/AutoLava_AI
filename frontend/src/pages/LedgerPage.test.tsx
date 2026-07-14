import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { LedgerPage } from "@/pages/LedgerPage";
import { StoreProvider } from "@/stores/StoreProvider";
import { LedgerForm } from "@/components/LedgerForm";
import { storeLocalToday } from "@/lib/user-api";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderLedger() {
  server.use(
    http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
    http.get("/api/database/1/records", () => HttpResponse.json({ items: [], categories: [
      { id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 },
      { id: 2, name: "刷卡", include_in_total: true, is_active: true, sort_order: 2 },
      { id: 3, name: "暗钱", include_in_total: false, is_active: true, sort_order: 3 },
    ], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 })),
    http.get("/api/ledger/1/recent", () => HttpResponse.json([])),
    http.get("/api/weather/1/:date", () => HttpResponse.json({ weather: null, weather_code: null, temperature_max: null, temperature_min: null, precipitation: null })),
    http.get("/api/ledger/1/:date", () => HttpResponse.json({ detail: "not found" }, { status: 404 })),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><StoreProvider><LedgerPage /></StoreProvider></QueryClientProvider>);
}

describe("LedgerPage", () => {
  it("calculates included-category cents and asks before overwriting with the same payload", async () => {
    let firstBody: unknown;
    let overwriteBody: unknown;
    server.use(http.put("/api/ledger/1/:date", async ({ request }) => {
      const body = await request.json();
      if (new URL(request.url).searchParams.get("overwrite") === "true") {
        overwriteBody = body;
        return HttpResponse.json({ id: 1, date: "2026-07-13", daily_revenue: "350.00" });
      }
      firstBody = body;
      return HttpResponse.json({ detail: "Record exists; confirm overwrite" }, { status: 409 });
    }));
    renderLedger();
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "200.10" } });
    fireEvent.change(screen.getByLabelText("刷卡"), { target: { value: "149.90" } });
    fireEvent.change(screen.getByLabelText("暗钱"), { target: { value: "80" } });
    expect(screen.getByText(/€350\.00/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("alertdialog", { name: "覆盖已有记录？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认覆盖" }));
    await waitFor(() => expect(overwriteBody).toEqual(firstBody));
  });

  it("normalizes rest amounts and wash count while keeping activity notes", async () => {
    let body: any;
    render(<LedgerForm categories={[{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }]} onSave={(value) => { body = value; }} />);
    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText("洗车数量"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("活动"), { target: { value: "设备检修" } });
    fireEvent.change(screen.getByLabelText("状态"), { target: { value: "休息" } });
    expect(screen.getByLabelText("活动")).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(body).toMatchObject({ is_open: "休息", wash_count: 0, activity: "设备检修", items: [{ category_id: 1, amount: "0" }] });
  });

  it("keeps a manually edited weather value when delayed automatic weather arrives", () => {
    const props = { categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], onSave: () => undefined };
    const view = render(<LedgerForm {...props} />);
    fireEvent.change(screen.getByLabelText("天气"), { target: { value: "手动天气" } });
    view.rerender(<LedgerForm {...props} weather={{ weather: "自动天气", weather_code: 1, temperature_max: 20, temperature_min: 10, precipitation: 0 }} />);
    expect(screen.getByLabelText("天气")).toHaveValue("手动天气");
  });

  it("uses the store timezone rather than browser UTC for today", () => {
    expect(storeLocalToday({ id: 1, name: "Honolulu", timezone: "Pacific/Honolulu" }, new Date("2026-07-14T01:00:00Z"))).toBe("2026-07-13");
  });

  it("scopes the category catalog to a newly selected historical date", async () => {
    const requested: string[] = [];
    renderLedger();
    const input = await screen.findByLabelText("日期");
    server.use(http.get("/api/database/1/records", ({ request }) => { requested.push(new URL(request.url).search); return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 }); }));
    fireEvent.change(input, { target: { value: "2026-06-01" } });
    await waitFor(() => expect(requested.some((query) => query.includes("start=2026-06-01") && query.includes("end=2026-06-01"))).toBe(true));
  });
});
