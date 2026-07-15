import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { LedgerPage } from "@/pages/LedgerPage";
import { StoreProvider, useStore } from "@/stores/StoreProvider";
import { LedgerForm } from "@/components/LedgerForm";
import { incomeConfigKey, storeLocalToday } from "@/lib/user-api";

const server = setupServer();
function StoreControls() { const { select } = useStore(); return <><button onClick={() => select(1)}>choose1</button><button onClick={() => select(2)}>choose2</button></>; }
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-07-15T10:00:00Z"));
});
afterEach(() => {
  server.resetHandlers();
  vi.useRealTimers();
});
afterAll(() => server.close());

function renderLedger(extra: Parameters<typeof server.use> = []) {
  server.use(
    ...extra,
    http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
    http.get("/api/income-config/1/current", () => HttpResponse.json({ store_id: 1, version_id: 4, version: 4, enabled: true, formula: "现金 + 刷卡", created_at: "2026-07-15T08:00:00", items: [
      { id: 11, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 },
      { id: 12, category_id: 2, name: "刷卡", include_in_total: true, is_active: true, sort_order: 2 },
      { id: 13, category_id: 3, name: "暗钱", include_in_total: false, is_active: true, sort_order: 3 },
    ] })),
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
  it("opens the shared calendar and selects a recorded historical date", async () => {
    renderLedger([
      http.get("/api/ledger/1/recent", () => HttpResponse.json([{ id: 7, date: "2026-07-14" }])),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" }));
    expect(screen.getByText("补记历史记录")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2026年7月14日，已有记录" }));

    const trigger = await screen.findByRole("button", { name: "选择台账日期：2026年7月14日" });
    fireEvent.click(trigger);
    expect(screen.getByText("编辑已有记录")).toBeInTheDocument();
  });

  it("loads the current income configuration for direct-total mode", async () => {
    let requested = "";
    renderLedger([
      http.get("/api/income-config/1/current", ({ request }) => {
        requested = new URL(request.url).pathname;
        return HttpResponse.json({ store_id: 1, version_id: null, version: 0, enabled: false, formula: "", created_at: null, items: [] });
      }),
    ]);

    expect(incomeConfigKey(1)).toEqual(["income-config", 1, "current"]);
    expect(await screen.findByLabelText("当日营业额")).toBeEnabled();
    expect(requested).toBe("/api/income-config/1/current");
  });

  it("shows a Chinese configuration error and retries only that dependency", async () => {
    let configCalls = 0;
    let catalogCalls = 0;
    renderLedger([
      http.get("/api/income-config/1/current", () => {
        configCalls += 1;
        return configCalls === 1
          ? HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 })
          : HttpResponse.json({ store_id: 1, version_id: null, version: 0, enabled: false, formula: "", created_at: null, items: [] });
      }),
      http.get("/api/database/1/records", () => {
        catalogCalls += 1;
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 });
      }),
    ]);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("服务器暂时不可用，请稍后重试");
    expect(alert).not.toHaveTextContent("Internal Server Error");
    fireEvent.click(screen.getByRole("button", { name: "重试收入配置" }));
    expect(await screen.findByLabelText("当日营业额")).toBeEnabled();
    expect(configCalls).toBe(2);
    expect(catalogCalls).toBe(1);
  });

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
    render(<LedgerForm config={{ store_id: 1, version_id: 4, version: 4, enabled: true, formula: "现金", created_at: "2026-07-15T08:00:00", items: [{ id: 11, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }] }} categories={[{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }]} onSave={(value) => { body = value; }} />);
    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText("洗车数量"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("活动"), { target: { value: "设备检修" } });
    fireEvent.change(screen.getByLabelText("状态"), { target: { value: "休息" } });
    expect(screen.getByLabelText("活动")).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(body).toMatchObject({ is_open: "休息", wash_count: 0, activity: "设备检修", items: [{ category_id: 1, amount: "0.00" }] });
  });

  it("keeps a manually edited weather value when delayed automatic weather arrives", () => {
    const props = { config: { store_id: 1, version_id: 4, version: 4, enabled: true, formula: "现金", created_at: "2026-07-15T08:00:00", items: [{ id: 11, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }] }, categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], onSave: () => undefined };
    const view = render(<LedgerForm {...props} />);
    fireEvent.change(screen.getByLabelText("天气"), { target: { value: "手动天气" } });
    view.rerender(<LedgerForm {...props} weather={{ weather: "自动天气", weather_code: 1, temperature_max: 20, temperature_min: 10, precipitation: 0 }} />);
    expect(screen.getByLabelText("天气")).toHaveValue("手动天气");
  });

  it("normalizes comma decimals and blocks invalid amounts with a visible error", () => {
    const saves: unknown[] = [];
    render(<LedgerForm config={{ store_id: 1, version_id: 4, version: 4, enabled: true, formula: "现金", created_at: "2026-07-15T08:00:00", items: [{ id: 11, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }] }} categories={[{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }]} onSave={(value) => saves.push(value)} />);
    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "12,3" } }); fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect((saves[0] as any).items[0].amount).toBe("12.30");
    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "-1" } });
    expect(screen.getByText("合计 —")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(screen.getByRole("alert")).toHaveTextContent("最多两位小数"); expect(saves).toHaveLength(1);
  });

  it("uses the store timezone rather than browser UTC for today", () => {
    expect(storeLocalToday({ id: 1, name: "Honolulu", timezone: "Pacific/Honolulu" }, new Date("2026-07-14T01:00:00Z"))).toBe("2026-07-13");
    expect(storeLocalToday({ id: 2, name: "Kiritimati", timezone: "Pacific/Kiritimati" }, new Date("2026-12-31T10:30:00Z"))).toBe("2027-01-01");
    expect(storeLocalToday({ id: 3, name: "New York", timezone: "America/New_York" }, new Date("2026-03-08T04:30:00Z"))).toBe("2026-03-07");
    expect(storeLocalToday({ id: 3, name: "New York", timezone: "America/New_York" }, new Date("2026-03-08T07:30:00Z"))).toBe("2026-03-08");
  });

  it("renders today and future disabling from the store timezone at a UTC boundary", async () => {
    vi.setSystemTime(new Date("2031-01-01T01:30:00Z"));
    renderLedger([
      http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Honolulu", timezone: "Pacific/Honolulu" }])),
    ]);

    const trigger = await screen.findByRole("button", { name: "选择台账日期：2030年12月31日" });
    fireEvent.click(trigger);
    expect(screen.getByRole("button", { name: "2031年1月1日" })).toBeDisabled();
  });

  it("scopes the category catalog to a newly selected historical date", async () => {
    const requested: string[] = [];
    renderLedger();
    server.use(http.get("/api/database/1/records", ({ request }) => { requested.push(new URL(request.url).search); return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 }); }));
    fireEvent.click(await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" }));
    fireEvent.click(screen.getByRole("button", { name: "上个月" }));
    fireEvent.click(screen.getByRole("button", { name: "2026年6月1日" }));
    await waitFor(() => expect(requested.some((query) => query.includes("start=2026-06-01") && query.includes("end=2026-06-01"))).toBe(true));
  });

  it("binds overwrite and invalidation to the original store and date across a store switch", async () => {
    let release!: () => void; const delayed = new Promise<void>((resolve) => { release = resolve; }); let overwriteUrl = "";
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "One", timezone: "Europe/Berlin" }, { id: 2, name: "Two", timezone: "Europe/Berlin" }])),
      http.get("/api/income-config/:store/current", ({ params }) => HttpResponse.json({ store_id: Number(params.store), version_id: 4, version: 4, enabled: true, formula: "现金", created_at: "2026-07-15T08:00:00", items: [{ id: 11, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }] })),
      http.get("/api/database/:store/records", () => HttpResponse.json({ items: [], categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 })),
      http.get("/api/ledger/:store/recent", () => HttpResponse.json([])), http.get("/api/weather/:store/:date", () => HttpResponse.json({ weather: null })), http.get("/api/ledger/:store/:date", () => HttpResponse.json({ detail: "not found" }, { status: 404 })),
      http.put("/api/ledger/:store/:date", async ({ request }) => { if (!new URL(request.url).searchParams.has("overwrite")) return HttpResponse.json({ detail: "exists" }, { status: 409 }); overwriteUrl = request.url; await delayed; return HttpResponse.json({}); }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><StoreProvider><StoreControls /><LedgerPage /></StoreProvider></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "choose1" })); fireEvent.click(await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" })); fireEvent.click(screen.getByRole("button", { name: "2026年7月13日" }));
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "1" } }); fireEvent.click(screen.getByRole("button", { name: "保存" })); await screen.findByRole("alertdialog");
    client.setQueryData(["dashboard", 1], true); client.setQueryData(["dashboard", 2], true); fireEvent.click(screen.getByRole("button", { name: "确认覆盖" })); fireEvent.click(screen.getByRole("button", { name: "choose2" })); release();
    await waitFor(() => expect(overwriteUrl).toContain("/api/ledger/1/2026-07-13?overwrite=true")); await waitFor(() => expect(client.getQueryState(["dashboard", 1])?.isInvalidated).toBe(true)); expect(client.getQueryState(["dashboard", 2])?.isInvalidated).toBe(false);
  });

  it("clears overwrite confirmation when the selected date changes", async () => {
    server.use(http.put("/api/ledger/1/:date", () => HttpResponse.json({ detail: "exists" }, { status: 409 })));
    renderLedger([http.get("/api/ledger/1/recent", () => HttpResponse.json([{ id: 8, date: "2026-07-13", is_open: "营业" }]))]);
    fireEvent.click(await screen.findByRole("button", { name: "保存" })); expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /2026-07-13/, hidden: true })); await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("shows recent loading failures separately and retries them", async () => {
    let calls = 0;
    renderLedger([http.get("/api/ledger/1/recent", () => { calls += 1; return calls === 1 ? HttpResponse.json({ detail: "Recent unavailable" }, { status: 500 }) : HttpResponse.json([]); })]);
    expect(await screen.findByRole("alert")).toHaveTextContent("Recent unavailable"); fireEvent.click(screen.getByRole("button", { name: "重试最近记录" })); await waitFor(() => expect(calls).toBe(2)); expect(screen.getByText("暂无记录")).toBeInTheDocument();
  });
});
