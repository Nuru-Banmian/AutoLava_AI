import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { LedgerPage } from "@/pages/LedgerPage";
import { StoreProvider, useStore } from "@/stores/StoreProvider";
import { LedgerForm } from "@/components/LedgerForm";
import { incomeConfigKey, ledgerMonthKey, storeLocalToday } from "@/lib/user-api";

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

function renderLedger(extra: Parameters<typeof server.use> = [], initialEntry = "/ledger") {
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
  return { ...render(<MemoryRouter initialEntries={[initialEntry]}><QueryClientProvider client={client}><StoreProvider><LedgerPage /></StoreProvider></QueryClientProvider></MemoryRouter>), client };
}

function recordSnapshot(amount: string, activity: string | null = null, weather: string | null = null) {
  return {
    id: 9, store_id: 1, date: "2026-07-15", daily_revenue: amount, income_mode: "composed", income_config_version_id: 4, row_version: 2,
    wash_count: null, is_open: "营业", weather, weather_auto: weather, weather_code: null, temperature_max: null, temperature_min: null, precipitation: null,
    activity, weather_edited: false, scanned: false, created_by: 1, updated_by: 1, created_at: "2026-07-15T08:00:00", updated_at: "2026-07-15T08:00:00",
    items: [
      { id: 21, category_id: 1, category_name: "现金", include_in_total: true, sort_order: 1, amount, created_at: "2026-07-15T08:00:00", updated_at: "2026-07-15T08:00:00" },
      { id: 22, category_id: 2, category_name: "刷卡", include_in_total: true, sort_order: 2, amount: "0.00", created_at: "2026-07-15T08:00:00", updated_at: "2026-07-15T08:00:00" },
      { id: 23, category_id: 3, category_name: "暗钱", include_in_total: false, sort_order: 3, amount: "0.00", created_at: "2026-07-15T08:00:00", updated_at: "2026-07-15T08:00:00" },
    ],
  };
}

describe("LedgerPage", () => {
  it("uses a valid date query parameter for the visible date and API requests", async () => {
    const requestedDates = new Set<string>();
    renderLedger([
      http.get("/api/database/1/records", ({ request }) => {
        const url = new URL(request.url);
        requestedDates.add(url.searchParams.get("start") ?? "");
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 });
      }),
      http.get("/api/ledger/1/:date", ({ params }) => {
        requestedDates.add(String(params.date));
        return HttpResponse.json({ detail: "not found" }, { status: 404 });
      }),
    ], "/ledger?date=2026-07-14");

    expect(await screen.findByRole("button", { name: "选择台账日期：2026年7月14日" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "补记历史记录" })).toBeEnabled();
    expect(requestedDates).toContain("2026-07-14");
  });

  it("rejects a future date query before any date-scoped request is sent", async () => {
    const futureRequests: string[] = [];
    renderLedger([
      http.get("/api/database/1/records", ({ request }) => {
        const url = new URL(request.url);
        const date = url.searchParams.get("start") ?? "";
        if (date > "2026-07-15") futureRequests.push(`categories:${date}`);
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 });
      }),
      http.get("/api/weather/1/:date", ({ params }) => {
        const date = String(params.date);
        if (date > "2026-07-15") futureRequests.push(`weather:${date}`);
        return HttpResponse.json({ weather: null });
      }),
      http.get("/api/ledger/1/:date", ({ params }) => {
        const date = String(params.date);
        if (date === "recent") return HttpResponse.json([]);
        if (date > "2026-07-15") futureRequests.push(`ledger:${date}`);
        return HttpResponse.json({ detail: "not found" }, { status: 404 });
      }),
    ], "/ledger?date=2026-07-16");

    expect(await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "保存今日记录" })).toBeEnabled();
    expect(futureRequests).toEqual([]);
  });

  it("never reuses the previous store date while switching across timezone day boundaries", async () => {
    vi.setSystemTime(new Date("2026-07-15T23:30:00Z"));
    const invalidStoreTwoRequests: string[] = [];
    const capture = (scope: string, store: string, date: string) => {
      if (store === "2" && date > "2026-07-15") invalidStoreTwoRequests.push(`${scope}:${date}`);
    };
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([
        { id: 1, name: "Berlin", timezone: "Europe/Berlin" },
        { id: 2, name: "New York", timezone: "America/New_York" },
      ])),
      http.get("/api/income-config/:store/current", ({ params }) => HttpResponse.json({ store_id: Number(params.store), version_id: null, version: 0, enabled: false, formula: "", created_at: null, items: [] })),
      http.get("/api/database/:store/records", ({ params, request }) => {
        capture("categories", String(params.store), new URL(request.url).searchParams.get("start") ?? "");
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 });
      }),
      http.get("/api/ledger/:store/recent", () => HttpResponse.json([])),
      http.get("/api/weather/:store/:date", ({ params }) => {
        capture("weather", String(params.store), String(params.date));
        return HttpResponse.json({ weather: null });
      }),
      http.get("/api/ledger/:store/:date", ({ params }) => {
        capture("ledger", String(params.store), String(params.date));
        return HttpResponse.json({ detail: "not found" }, { status: 404 });
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<MemoryRouter><QueryClientProvider client={client}><StoreProvider><StoreControls /><LedgerPage /></StoreProvider></QueryClientProvider></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "choose1" }));
    expect(await screen.findByRole("button", { name: "选择台账日期：2026年7月16日" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "保存今日记录" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "choose2" }));
    expect(await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "保存今日记录" })).toBeEnabled();
    expect(invalidStoreTwoRequests).toEqual([]);
  });

  it("keeps income visible while weather and wash/activity start collapsed", async () => {
    renderLedger();

    expect(await screen.findByRole("group", { name: "收入项目" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "天气" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "洗车数量 / 活动" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("天气")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("洗车数量")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存今日记录" })).toBeEnabled();
  });

  it("opens the shared calendar and selects a recorded historical date", async () => {
    renderLedger([
      http.get("/api/database/1/records", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("page_size") === "200") return HttpResponse.json({ items: [{ id: 7, date: "2026-07-14" }], categories: [], sum_daily_revenue: "0.00", total: 1, page: 1, page_size: 200 });
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 });
      }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" }));
    expect(screen.getByText("补记历史记录")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "2026年7月14日，已有记录" }));

    const trigger = await screen.findByRole("button", { name: "选择台账日期：2026年7月14日" });
    fireEvent.click(trigger);
    expect(screen.getByText("编辑已有记录")).toBeInTheDocument();
  });

  it("autofills a calendar-selected saved record and preserves untouched fields on modification", async () => {
    const historicalRecord = {
      ...recordSnapshot("88.50", "周末促销", "小雨"),
      date: "2026-07-14",
      is_open: "天气停业" as const,
      wash_count: 17,
      items: [
        { id: 21, category_id: 1, category_name: "现金", include_in_total: true, sort_order: 1, amount: "88.50", created_at: "2026-07-14T08:00:00", updated_at: "2026-07-14T08:00:00" },
        { id: 22, category_id: 2, category_name: "刷卡", include_in_total: true, sort_order: 2, amount: "12.30", created_at: "2026-07-14T08:00:00", updated_at: "2026-07-14T08:00:00" },
        { id: 23, category_id: 3, category_name: "暗钱", include_in_total: false, sort_order: 3, amount: "4.50", created_at: "2026-07-14T08:00:00", updated_at: "2026-07-14T08:00:00" },
      ],
    };
    let submitted: unknown;
    renderLedger([
      http.get("/api/database/1/records", ({ request }) => {
        if (new URL(request.url).searchParams.get("page_size") === "200") return HttpResponse.json({ items: [{ id: 9, date: "2026-07-14" }], categories: [], sum_daily_revenue: "105.30", total: 1, page: 1, page_size: 200 });
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 });
      }),
      http.get("/api/ledger/1/:date", ({ params }) => {
        if (params.date === "recent") return HttpResponse.json([]);
        return params.date === "2026-07-14" ? HttpResponse.json(historicalRecord) : HttpResponse.json({ detail: "not found" }, { status: 404 });
      }),
      http.put("/api/ledger/1/2026-07-14", async ({ request }) => {
        submitted = await request.json();
        return HttpResponse.json(historicalRecord);
      }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" }));
    fireEvent.click(await screen.findByRole("button", { name: "2026年7月14日，已有记录" }));

    expect(await screen.findByRole("button", { name: "保存修改" })).toBeEnabled();
    expect(screen.getByLabelText("状态")).toHaveValue("天气停业");
    expect(screen.getByLabelText("现金")).toHaveValue("88.50");
    expect(screen.getByLabelText("刷卡")).toHaveValue("12.30");
    fireEvent.click(screen.getByRole("button", { name: "天气" }));
    expect(screen.getByLabelText("天气")).toHaveValue("小雨");
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    expect(screen.getByLabelText("洗车数量")).toHaveValue(17);
    expect(screen.getByLabelText("活动")).toHaveValue("周末促销");

    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "99.9" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    await waitFor(() => expect(submitted).toEqual({
      is_open: "天气停业", daily_revenue: null, config_version_id: 4, expected_version: 2,
      wash_count: 17, weather: "小雨", weather_edited: false, activity: "周末促销",
      items: [{ category_id: 1, amount: "99.90" }, { category_id: 2, amount: "12.30" }, { category_id: 3, amount: "4.50" }],
    }));
  });

  it("loads markers for the calendar month currently being viewed", async () => {
    renderLedger([
      http.get("/api/database/1/records", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("start") === "2026-06-01") {
          expect(url.searchParams.get("end")).toBe("2026-06-30");
          expect(url.searchParams.get("page_size")).toBe("200");
          return HttpResponse.json({ items: [{ id: 7, date: "2026-06-04" }], categories: [], sum_daily_revenue: "0.00", total: 1, page: 1, page_size: 200 });
        }
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 });
      }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" }));
    fireEvent.click(screen.getByRole("button", { name: "上个月" }));

    expect(await screen.findByRole("button", { name: "2026年6月4日，已有记录" })).toBeEnabled();
  });

  it("reopens the picker with only the selected date month marker request", async () => {
    const markerMonths: string[] = [];
    renderLedger([
      http.get("/api/database/1/records", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("page_size") === "200") markerMonths.push(url.searchParams.get("start")!);
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 });
      }),
    ]);

    const trigger = await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" });
    fireEvent.click(trigger);
    await waitFor(() => expect(markerMonths).toContain("2026-07-01"));
    fireEvent.click(screen.getByRole("button", { name: "上个月" }));
    await waitFor(() => expect(markerMonths).toContain("2026-06-01"));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "选择台账日期" })).not.toBeInTheDocument());

    markerMonths.length = 0;
    fireEvent.click(trigger);

    expect(screen.getByText("2026年7月")).toBeInTheDocument();
    await waitFor(() => expect(markerMonths).toEqual(["2026-07-01"]));
  });

  it("only requests visible-month markers while the picker is open and refetches after a closed-save invalidation", async () => {
    let saved = false;
    let monthRequests = 0;
    const { client } = renderLedger([
      http.get("/api/database/1/records", ({ request }) => {
        if (new URL(request.url).searchParams.get("page_size") === "200") {
          monthRequests += 1;
          return HttpResponse.json({ items: saved ? [{ id: 7, date: "2026-07-15" }] : [], categories: [], sum_daily_revenue: "0.00", total: saved ? 1 : 0, page: 1, page_size: 200 });
        }
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 });
      }),
      http.put("/api/ledger/1/:date", () => {
        saved = true;
        return HttpResponse.json({ id: 9, date: "2026-07-15" });
      }),
    ]);

    const trigger = await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" });
    expect(monthRequests).toBe(0);
    fireEvent.click(trigger);
    await waitFor(() => expect(monthRequests).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "选择台账日期" })).not.toBeInTheDocument());

    fireEvent.click(await screen.findByRole("button", { name: "保存今日记录" }));
    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    expect(client.getQueryState(ledgerMonthKey(1, "2026-07"))?.isInvalidated).toBe(true);
    expect(monthRequests).toBe(1);

    fireEvent.click(trigger);
    await waitFor(() => expect(monthRequests).toBe(2));
    expect(await screen.findByRole("button", { name: "2026年7月15日，已有记录" })).toBeEnabled();
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
      http.get("/api/database/1/records", ({ request }) => {
        if (new URL(request.url).searchParams.get("page_size") === "1") catalogCalls += 1;
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

  it("refetches config and record after a version conflict without losing entered amounts", async () => {
    let configCalls = 0;
    let recordCalls = 0;
    renderLedger([
      http.get("/api/income-config/1/current", () => {
        configCalls += 1;
        return HttpResponse.json({ store_id: 1, version_id: 4, version: 4, enabled: true, formula: "现金", created_at: "2026-07-15T08:00:00", items: [{ id: 11, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }] });
      }),
      http.get("/api/ledger/1/:date", ({ params }) => {
        if (params.date === "recent") return HttpResponse.json([]);
        recordCalls += 1;
        return recordCalls === 1 ? HttpResponse.json({ detail: "not found" }, { status: 404 }) : HttpResponse.json(recordSnapshot("999.00"));
      }),
      http.put("/api/ledger/1/:date", () => HttpResponse.json({ detail: "Income configuration version does not match" }, { status: 409 })),
    ]);

    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "123.45" } });
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("收入项目刚刚发生变化");
    expect(screen.getByRole("alert")).not.toHaveTextContent("Income configuration version does not match");
    await waitFor(() => expect(configCalls).toBe(2));
    await waitFor(() => expect(recordCalls).toBe(2));
    expect(screen.getByLabelText("现金")).toHaveValue("123.45");
    expect(screen.queryByRole("alertdialog", { name: "覆盖已有记录？" })).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
    expect(await screen.findByRole("alertdialog", { name: "覆盖已有记录？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认覆盖" }));
    await waitFor(() => expect(overwriteBody).toEqual(firstBody));
  });

  it("normalizes rest amounts and wash count while keeping activity notes", async () => {
    let body: any;
    render(<LedgerForm config={{ store_id: 1, version_id: 4, version: 4, enabled: true, formula: "现金", created_at: "2026-07-15T08:00:00", items: [{ id: 11, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }] }} categories={[{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }]} onSave={(value) => { body = value; }} />);
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText("洗车数量"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("活动"), { target: { value: "设备检修" } });
    fireEvent.change(screen.getByLabelText("状态"), { target: { value: "休息" } });
    expect(screen.getByLabelText("活动")).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(body).toMatchObject({ is_open: "休息", wash_count: 0, activity: "设备检修", items: [{ category_id: 1, amount: "0.00" }] });
  });

  it("reports edits against the loaded snapshot and preserves collapsed values", async () => {
    const onDirtyChange = vi.fn();
    render(<LedgerForm config={{ store_id: 1, version_id: 4, version: 4, enabled: true, formula: "现金", created_at: "2026-07-15T08:00:00", items: [{ id: 11, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }] }} categories={[{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }]} onSave={() => undefined} onDirtyChange={onDirtyChange} />);

    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    fireEvent.change(screen.getByLabelText("活动"), { target: { value: "夏日活动" } });
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    expect(screen.getByLabelText("活动")).toHaveValue("夏日活动");
  });

  it("accepts a saved submission only after the form is clean", async () => {
    const events: string[] = [];
    const props = {
      config: { store_id: 1, version_id: null, version: 0, enabled: false, formula: "", created_at: null, items: [] },
      categories: [],
      onSave: vi.fn(),
      onDirtyChange: (dirty: boolean) => events.push(`dirty:${dirty}`),
      onSavedSubmissionApplied: (revision: number) => events.push(`saved:${revision}`),
    };
    const view = render(<LedgerForm {...props} />);
    fireEvent.change(screen.getByLabelText("当日营业额"), { target: { value: "66" } });
    view.rerender(<LedgerForm {...props} savedSubmission={{ revision: 1, body: {
      is_open: "营业", daily_revenue: "66.00", config_version_id: null,
      expected_version: null, wash_count: null, weather: null,
      weather_edited: false, activity: null, items: [],
    } }} />);

    await waitFor(() => expect(events.slice(-2)).toEqual(["dirty:false", "saved:1"]));
  });

  it("keeps a manually edited weather value when delayed automatic weather arrives", () => {
    const props = { config: { store_id: 1, version_id: 4, version: 4, enabled: true, formula: "现金", created_at: "2026-07-15T08:00:00", items: [{ id: 11, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }] }, categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], onSave: () => undefined };
    const view = render(<LedgerForm {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "天气" }));
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

  it("confirms before discarding edits when changing the ledger date", async () => {
    renderLedger([http.get("/api/ledger/1/recent", () => HttpResponse.json([{ id: 8, date: "2026-07-13", is_open: "营业" }]))]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "88" } });

    fireEvent.click(screen.getByRole("button", { name: /2026-07-13/ }));
    expect(await screen.findByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByRole("button", { name: "选择台账日期：2026年7月15日" })).toBeInTheDocument();
    expect(screen.getByLabelText("现金")).toHaveValue("88");

    fireEvent.click(screen.getByRole("button", { name: /2026-07-13/ }));
    fireEvent.click(await screen.findByRole("button", { name: "放弃修改" }));
    expect(await screen.findByRole("button", { name: "选择台账日期：2026年7月13日" })).toBeInTheDocument();
  });

  it("stops blocking navigation after a successful save", async () => {
    renderLedger([
      http.get("/api/ledger/1/recent", () => HttpResponse.json([{ id: 8, date: "2026-07-13", is_open: "营业" }])),
      http.put("/api/ledger/1/:date", () => HttpResponse.json({ id: 9, date: "2026-07-15" })),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "66" } });
    const dirtyEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirtyEvent);
    expect(dirtyEvent.defaultPrevented).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    const savedEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(savedEvent);
    expect(savedEvent.defaultPrevented).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /2026-07-13/ }));
    expect(screen.queryByRole("alertdialog", { name: "放弃未保存的修改？" })).not.toBeInTheDocument();
  });

  it("changes date without a warning after the saved baseline is applied", async () => {
    renderLedger([
      http.get("/api/database/1/records", ({ request }) =>
        new URL(request.url).searchParams.get("page_size") === "200"
          ? HttpResponse.json({ items: [{ id: 8, date: "2026-07-13" }], categories: [], sum_daily_revenue: "0.00", total: 1, page: 1, page_size: 200 })
          : HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 })),
      http.put("/api/ledger/1/:date", () => HttpResponse.json(recordSnapshot("66.00"))),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "66" } });
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    fireEvent.click(screen.getByRole("button", { name: "选择台账日期：2026年7月15日" }));
    fireEvent.click(await screen.findByRole("button", { name: "2026年7月13日，已有记录" }));
    expect(screen.queryByRole("alertdialog", { name: "放弃未保存的修改？" })).not.toBeInTheDocument();
  });

  it("stays clean after an existing record is saved and refetched canonically", async () => {
    let saved = false;
    renderLedger([
      http.get("/api/ledger/1/:date", ({ params }) => params.date === "recent" ? HttpResponse.json([]) : HttpResponse.json(recordSnapshot(saved ? "12.30" : "12.00", saved ? "促销" : null))),
      http.put("/api/ledger/1/:date", async ({ request }) => {
        const body = await request.json() as any;
        expect(body.items[0].amount).toBe("12.30");
        expect(body.activity).toBe("促销");
        saved = true;
        return HttpResponse.json(recordSnapshot("12.30", "促销"));
      }),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "12,3" } });
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    fireEvent.change(screen.getByLabelText("活动"), { target: { value: " 促销 " } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    await waitFor(() => expect(saved).toBe(true));

    await waitFor(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false);
    });
  });

  it("waits for the post-save record before absorbing delayed automatic weather", async () => {
    let releaseWeather!: () => void;
    const weatherDelayed = new Promise<void>((resolve) => { releaseWeather = resolve; });
    let releaseRecord!: () => void;
    const recordDelayed = new Promise<void>((resolve) => { releaseRecord = resolve; });
    let recordCalls = 0;
    let weatherReturned = false;
    renderLedger([
      http.get("/api/weather/1/:date", async () => { await weatherDelayed; weatherReturned = true; return HttpResponse.json({ weather: "晴" }); }),
      http.get("/api/ledger/1/:date", async ({ params }) => {
        if (params.date === "recent") return HttpResponse.json([]);
        recordCalls += 1;
        if (recordCalls === 1) return HttpResponse.json({ detail: "not found" }, { status: 404 });
        await recordDelayed;
        return HttpResponse.json(recordSnapshot("10.00", null, "晴"));
      }),
      http.put("/api/ledger/1/:date", () => HttpResponse.json(recordSnapshot("10.00", null, "晴"))),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    fireEvent.click(screen.getByRole("button", { name: "天气" }));
    await waitFor(() => expect(recordCalls).toBe(2));

    await act(async () => { releaseWeather(); });
    await waitFor(() => expect(weatherReturned).toBe(true));
    expect(screen.getByLabelText("天气")).toHaveValue("");
    const intermediateEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(intermediateEvent);
    expect(intermediateEvent.defaultPrevented).toBe(false);

    await act(async () => { releaseRecord(); });
    await waitFor(() => expect(screen.getByLabelText("天气")).toHaveValue("晴"));

    await waitFor(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false);
    });
  });

  it("keeps the submitted baseline when the post-save record refetch fails", async () => {
    let recordCalls = 0;
    renderLedger([
      http.get("/api/ledger/1/:date", ({ params }) => {
        if (params.date === "recent") return HttpResponse.json([]);
        recordCalls += 1;
        if (recordCalls === 1) return HttpResponse.json(recordSnapshot("5.00"));
        return recordCalls === 2 ? HttpResponse.json({ detail: "failed" }, { status: 500 }) : HttpResponse.json(recordSnapshot("10.00", null, "晴"));
      }),
      http.put("/api/ledger/1/:date", () => HttpResponse.json(recordSnapshot("10.00"))),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    await waitFor(() => expect(recordCalls).toBe(2));

    expect(screen.getByLabelText("现金")).toHaveValue("10");
    await waitFor(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false);
    });

    fireEvent.click(screen.getByRole("button", { name: "重试台账" }));
    fireEvent.click(screen.getByRole("button", { name: "天气" }));
    await waitFor(() => expect(screen.getByLabelText("天气")).toHaveValue("晴"));
  });

  it("keeps a newly created record retryable when its post-save refetch fails", async () => {
    let recordCalls = 0;
    renderLedger([
      http.get("/api/ledger/1/:date", ({ params }) => {
        if (params.date === "recent") return HttpResponse.json([]);
        recordCalls += 1;
        if (recordCalls === 1) return HttpResponse.json({ detail: "not found" }, { status: 404 });
        return recordCalls === 2 ? HttpResponse.json({ detail: "failed" }, { status: 500 }) : HttpResponse.json(recordSnapshot("10.00", null, "晴"));
      }),
      http.put("/api/ledger/1/:date", () => HttpResponse.json({ id: 9, date: "2026-07-15", daily_revenue: "10.00", row_version: 2 })),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    await waitFor(() => expect(recordCalls).toBe(2));

    expect(screen.getByLabelText("现金")).toHaveValue("10");
    expect(screen.getByRole("alert")).toHaveTextContent("台账刷新失败，请稍后重试");
    const savedEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(savedEvent);
    expect(savedEvent.defaultPrevented).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "重试台账" }));
    fireEvent.click(screen.getByRole("button", { name: "天气" }));
    await waitFor(() => expect(screen.getByLabelText("天气")).toHaveValue("晴"));
    const canonicalEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(canonicalEvent);
    expect(canonicalEvent.defaultPrevented).toBe(false);
  });

  it("keeps edits made while a save is pending after success and record refetch", async () => {
    let release!: () => void;
    const delayed = new Promise<void>((resolve) => { release = resolve; });
    let saved = false;
    renderLedger([
      http.get("/api/ledger/1/recent", () => HttpResponse.json([{ id: 8, date: "2026-07-13", is_open: "营业" }])),
      http.get("/api/ledger/1/:date", ({ params }) => params.date === "recent" ? HttpResponse.json([]) : saved ? HttpResponse.json(recordSnapshot("10.00")) : HttpResponse.json({ detail: "not found" }, { status: 404 })),
      http.put("/api/ledger/1/:date", async () => { await delayed; saved = true; return HttpResponse.json(recordSnapshot("10.00")); }),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "20" } });
    release();
    await waitFor(() => expect(saved).toBe(true));
    await waitFor(() => expect(screen.getByLabelText("现金")).toHaveValue("20"));

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /2026-07-13/ }));
    expect(await screen.findByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
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
    render(<MemoryRouter><QueryClientProvider client={client}><StoreProvider><StoreControls /><LedgerPage /></StoreProvider></QueryClientProvider></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "choose1" })); fireEvent.click(await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" })); fireEvent.click(screen.getByRole("button", { name: "2026年7月13日" }));
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "1" } }); fireEvent.click(screen.getByRole("button", { name: "补记历史记录" })); await screen.findByRole("alertdialog");
    client.setQueryData(["dashboard", 1], true); client.setQueryData(["dashboard", 2], true); fireEvent.click(screen.getByRole("button", { name: "确认覆盖" })); fireEvent.click(screen.getByRole("button", { name: "choose2" })); release();
    await waitFor(() => expect(overwriteUrl).toContain("/api/ledger/1/2026-07-13?overwrite=true")); await waitFor(() => expect(client.getQueryState(["dashboard", 1])?.isInvalidated).toBe(true)); expect(client.getQueryState(["dashboard", 2])?.isInvalidated).toBe(false);
  });

  it("confirms before discarding edits when switching stores", async () => {
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "One", timezone: "Europe/Berlin" }, { id: 2, name: "Two", timezone: "Europe/Berlin" }])),
      http.get("/api/income-config/:store/current", ({ params }) => HttpResponse.json({ store_id: Number(params.store), version_id: 4, version: 4, enabled: true, formula: "现金", created_at: "2026-07-15T08:00:00", items: [{ id: 11, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }] })),
      http.get("/api/database/:store/records", () => HttpResponse.json({ items: [], categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], sum_daily_revenue: "0", total: 0, page: 1, page_size: 1 })),
      http.get("/api/ledger/:store/recent", () => HttpResponse.json([])),
      http.get("/api/weather/:store/:date", () => HttpResponse.json({ weather: null })),
      http.get("/api/ledger/:store/:date", () => HttpResponse.json({ detail: "not found" }, { status: 404 })),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<MemoryRouter><QueryClientProvider client={client}><StoreProvider><StoreControls /><LedgerPage /></StoreProvider></QueryClientProvider></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "choose1" }));
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "77" } });

    fireEvent.click(screen.getByRole("button", { name: "choose2" }));
    expect(await screen.findByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("现金")).toHaveValue("77");

    fireEvent.click(screen.getByRole("button", { name: "choose2" }));
    fireEvent.click(await screen.findByRole("button", { name: "放弃修改" }));
    await waitFor(() => expect(screen.getByLabelText("现金")).toHaveValue("0"));
  });

  it("clears overwrite confirmation when the selected date changes", async () => {
    server.use(http.put("/api/ledger/1/:date", () => HttpResponse.json({ detail: "exists" }, { status: 409 })));
    renderLedger([http.get("/api/ledger/1/recent", () => HttpResponse.json([{ id: 8, date: "2026-07-13", is_open: "营业" }]))]);
    fireEvent.click(await screen.findByRole("button", { name: "保存今日记录" })); expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /2026-07-13/, hidden: true })); await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("shows recent loading failures separately and retries them", async () => {
    let calls = 0;
    renderLedger([http.get("/api/ledger/1/recent", () => { calls += 1; return calls === 1 ? HttpResponse.json({ detail: "Recent unavailable" }, { status: 500 }) : HttpResponse.json([]); })]);
    expect(await screen.findByRole("alert")).toHaveTextContent("服务器暂时不可用，请稍后重试"); fireEvent.click(screen.getByRole("button", { name: "重试最近记录" })); await waitFor(() => expect(calls).toBe(2)); expect(screen.getByText("暂无记录")).toBeInTheDocument();
  });
});
