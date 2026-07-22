import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, useLocation } from "react-router-dom";
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

type TestInitialEntry = string | { pathname: string; search?: string; state?: unknown };

function LocationProbe() {
  const location = useLocation();
  return <div aria-label="当前位置">{location.pathname}{location.search}</div>;
}

function renderLedger(extra: Parameters<typeof server.use> = [], initialEntry: TestInitialEntry = "/ledger") {
  server.use(
    ...extra,
    http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
    http.get("/api/income-config/1/current", () => HttpResponse.json({ store_id: 1, enabled: true, formula: "现金 + 刷卡", items: [
      { id: 1, store_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1, archived_at: null },
      { id: 2, store_id: 1, name: "刷卡", include_in_total: true, is_active: true, sort_order: 2, archived_at: null },
      { id: 3, store_id: 1, name: "暗钱", include_in_total: false, is_active: true, sort_order: 3, archived_at: null },
    ] })),
    http.get("/api/database/1/records", () => HttpResponse.json({ items: [], categories: [
      { id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 },
      { id: 2, name: "刷卡", include_in_total: true, is_active: true, sort_order: 2 },
      { id: 3, name: "暗钱", include_in_total: false, is_active: true, sort_order: 3 },
    ], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 })),
    http.get("/api/ledger/1/recent", () => HttpResponse.json([])),
    http.get("/api/weather/1/:date", () => HttpResponse.json({ weather: null, weather_code: null, temperature_max: null, temperature_min: null, precipitation: null })),
    http.get("/api/ledger/1/:date", () => HttpResponse.json({ detail: "not found" }, { status: 404 })),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { ...render(<MemoryRouter initialEntries={[initialEntry]}><QueryClientProvider client={client}><StoreProvider><LedgerPage /><LocationProbe /></StoreProvider></QueryClientProvider></MemoryRouter>), client };
}

function fillBlankLedgerAmounts() {
  for (const input of document.querySelectorAll<HTMLInputElement>('input[inputmode="numeric"]')) {
    if (input.value === "") fireEvent.change(input, { target: { value: "0" } });
  }
}

async function chooseRecordWeather(value: string) {
  fireEvent.pointerDown(screen.getByRole("combobox", { name: "天气" }), { button: 0, ctrlKey: false, pointerType: "mouse" });
  await waitFor(() => expect(document.querySelectorAll('[role="option"]')).toHaveLength(28));
  const option = [...document.querySelectorAll<HTMLElement>('[role="option"]')].find((candidate) => candidate.textContent === value);
  expect(option).toBeDefined();
  fireEvent.click(option!);
}

function recordSnapshot(amount: number, activity: string | null = null, weather: string | null = null) {
  return {
    id: 9, store_id: 1, date: "2026-07-15", daily_revenue: amount, income_mode: "composed",
    wash_count: null, is_open: "营业", weather, weather_auto: weather, weather_code: null, temperature_max: null, temperature_min: null, precipitation: null,
    activity, weather_edited: false, scanned: false, created_by: 1, updated_by: 1, created_at: "2026-07-15T08:00:00", updated_at: "2026-07-15T08:00:00",
    items: [
      { id: 21, category_id: 1, category_name: "现金", include_in_total: true, sort_order: 1, amount, created_at: "2026-07-15T08:00:00", updated_at: "2026-07-15T08:00:00" },
      { id: 22, category_id: 2, category_name: "刷卡", include_in_total: true, sort_order: 2, amount: 0, created_at: "2026-07-15T08:00:00", updated_at: "2026-07-15T08:00:00" },
      { id: 23, category_id: 3, category_name: "暗钱", include_in_total: false, sort_order: 3, amount: 0, created_at: "2026-07-15T08:00:00", updated_at: "2026-07-15T08:00:00" },
    ],
  };
}

const singleConfig = {
  store_id: 1,
  enabled: true,
  formula: "现金",
  items: [{ id: 1, store_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1, archived_at: null }],
};

describe("LedgerPage", () => {
  it("uses a valid date query parameter for the visible date and API requests", async () => {
    const requestedDates = new Set<string>();
    renderLedger([
      http.get("/api/database/1/records", ({ request }) => {
        const url = new URL(request.url);
        requestedDates.add(url.searchParams.get("start") ?? "");
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 });
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
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 });
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
      http.get("/api/income-config/:store/current", ({ params }) => HttpResponse.json({ store_id: Number(params.store), enabled: false, formula: "", items: [] })),
      http.get("/api/database/:store/records", ({ params, request }) => {
        capture("categories", String(params.store), new URL(request.url).searchParams.get("start") ?? "");
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 });
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

  it("keeps income and weather visible while wash/activity starts collapsed", async () => {
    renderLedger();

    expect(await screen.findByRole("group", { name: "收入项目" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "天气" })).toHaveTextContent("请选择天气");
    expect(screen.getByRole("button", { name: "洗车数量 / 活动" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("洗车数量")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存今日记录" })).toBeEnabled();
  });

  it("opens the shared calendar and selects a recorded historical date", async () => {
    renderLedger([
      http.get("/api/database/1/records", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("page_size") === "200") return HttpResponse.json({ items: [{ id: 7, date: "2026-07-14" }], categories: [], sum_daily_revenue: 0, total: 1, page: 1, page_size: 200 });
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 });
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
      ...recordSnapshot(101, "周末促销", "中雨"),
      date: "2026-07-14",
      is_open: "天气停业" as const,
      wash_count: 17,
      items: [
        { id: 21, category_id: 1, category_name: "现金", include_in_total: true, sort_order: 1, amount: 89, created_at: "2026-07-14T08:00:00", updated_at: "2026-07-14T08:00:00" },
        { id: 22, category_id: 2, category_name: "刷卡", include_in_total: true, sort_order: 2, amount: 12, created_at: "2026-07-14T08:00:00", updated_at: "2026-07-14T08:00:00" },
        { id: 23, category_id: 3, category_name: "暗钱", include_in_total: false, sort_order: 3, amount: 5, created_at: "2026-07-14T08:00:00", updated_at: "2026-07-14T08:00:00" },
      ],
    };
    let submitted: unknown;
    renderLedger([
      http.get("/api/database/1/records", ({ request }) => {
        if (new URL(request.url).searchParams.get("page_size") === "200") return HttpResponse.json({ items: [{ id: 9, date: "2026-07-14" }], categories: [], sum_daily_revenue: 101, total: 1, page: 1, page_size: 200 });
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 });
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
    expect(screen.getByLabelText("现金")).toHaveValue("89");
    expect(screen.getByLabelText("刷卡")).toHaveValue("12");
    expect(screen.getByRole("combobox", { name: "天气" })).toHaveTextContent("中雨");
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    expect(screen.getByLabelText("洗车数量")).toHaveValue(17);
    expect(screen.getByLabelText("活动")).toHaveValue("周末促销");

    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "100" } });
    fillBlankLedgerAmounts();
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    await waitFor(() => expect(submitted).toEqual({
      is_open: "天气停业", daily_revenue: null,
      wash_count: 17, weather: "中雨", weather_edited: false, activity: "周末促销",
      items: [{ category_id: 1, amount: 100 }, { category_id: 2, amount: 12 }, { category_id: 3, amount: 5 }],
    }));
  });

  it("loads markers for the calendar month currently being viewed", async () => {
    renderLedger([
      http.get("/api/database/1/records", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("start") === "2026-06-01") {
          expect(url.searchParams.get("end")).toBe("2026-06-30");
          expect(url.searchParams.get("page_size")).toBe("200");
          return HttpResponse.json({ items: [{ id: 7, date: "2026-06-04" }], categories: [], sum_daily_revenue: 0, total: 1, page: 1, page_size: 200 });
        }
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 });
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
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 });
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
          return HttpResponse.json({ items: saved ? [{ id: 7, date: "2026-07-15" }] : [], categories: [], sum_daily_revenue: 0, total: saved ? 1 : 0, page: 1, page_size: 200 });
        }
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 });
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

    fillBlankLedgerAmounts();
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
        return HttpResponse.json({ store_id: 1, enabled: false, formula: "", items: [] });
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
          : HttpResponse.json({ store_id: 1, enabled: false, formula: "", items: [] });
      }),
      http.get("/api/database/1/records", ({ request }) => {
        if (new URL(request.url).searchParams.get("page_size") === "1") catalogCalls += 1;
        return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 });
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

  it("puts once with integer amounts and no overwrite or version fields", async () => {
    let requestUrl = "";
    let submitted: Record<string, unknown> | null = null;
    server.use(http.put("/api/ledger/1/:date", async ({ request }) => {
      requestUrl = request.url;
      submitted = await request.json() as Record<string, unknown>;
      return HttpResponse.json({ id: 1, date: "2026-07-15", daily_revenue: 350 });
    }));
    renderLedger();
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "200" } });
    fireEvent.change(screen.getByLabelText("刷卡"), { target: { value: "150" } });
    fireEvent.change(screen.getByLabelText("暗钱"), { target: { value: "80" } });
    expect(screen.getByText("合计 €350")).toBeInTheDocument();
    fillBlankLedgerAmounts();
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
    await waitFor(() => expect(submitted).not.toBeNull());
    expect(new URL(requestUrl).search).toBe("");
    expect(submitted).not.toHaveProperty("config_version_id");
    expect(submitted).not.toHaveProperty("expected_version");
    expect(screen.queryByText(/覆盖/)).not.toBeInTheDocument();
  });

  it("returns to Business Records after a successful records-launched save", async () => {
    renderLedger([
      http.put("/api/ledger/1/:date", () => HttpResponse.json({ id: 9, date: "2026-07-15", daily_revenue: 1 })),
    ], {
      pathname: "/ledger",
      search: "?date=2026-07-15",
      state: {
        returnToBusinessRecords: {
          storeId: 1,
          recordMode: "current-month",
          range: { start: "2026-07-01", end: "2026-07-31" },
          page: 1,
          selectedDate: "2026-07-15",
          mobileRecordDate: null,
          scrollY: 0,
        },
      },
    });
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "1" } });
    fillBlankLedgerAmounts();
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));

    await waitFor(() => expect(screen.getByLabelText("当前位置")).toHaveTextContent("/database"));
  });

  it("stays on the ledger when the saved date is outside the source record range", async () => {
    renderLedger([
      http.put("/api/ledger/1/:date", () => HttpResponse.json({ id: 9, date: "2026-07-15", daily_revenue: 1 })),
    ], {
      pathname: "/ledger",
      search: "?date=2026-07-15",
      state: {
        returnToBusinessRecords: {
          storeId: 1,
          recordMode: "previous-month",
          range: { start: "2026-06-01", end: "2026-06-30" },
          page: 1,
          selectedDate: null,
          mobileRecordDate: null,
          scrollY: 0,
        },
      },
    });
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "1" } });
    fillBlankLedgerAmounts();
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));

    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    expect(screen.getByLabelText("当前位置")).toHaveTextContent("/ledger?date=2026-07-15");
  });

  it("stays on the ledger after a direct successful save", async () => {
    renderLedger([
      http.put("/api/ledger/1/:date", () => HttpResponse.json({ id: 9, date: "2026-07-15", daily_revenue: 1 })),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "1" } });
    fillBlankLedgerAmounts();
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));

    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    expect(screen.getByLabelText("当前位置")).toHaveTextContent("/ledger");
  });

  it("ignores an invalid return snapshot after a successful save", async () => {
    renderLedger([
      http.put("/api/ledger/1/:date", () => HttpResponse.json({ id: 9, date: "2026-07-15", daily_revenue: 1 })),
    ], {
      pathname: "/ledger",
      search: "?date=2026-07-15",
      state: { returnToBusinessRecords: { storeId: 1 } },
    });
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "7" } });
    fillBlankLedgerAmounts();
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));

    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    expect(screen.getByLabelText("当前位置")).toHaveTextContent("/ledger?date=2026-07-15");
  });

  it("keeps source-launched input and error feedback after a failed save", async () => {
    renderLedger([
      http.put("/api/ledger/1/:date", () => HttpResponse.json({ detail: "failed" }, { status: 500 })),
    ], {
      pathname: "/ledger",
      search: "?date=2026-07-15",
      state: {
        returnToBusinessRecords: {
          storeId: 1,
          recordMode: "current-month",
          range: { start: "2026-07-01", end: "2026-07-31" },
          page: 1,
          selectedDate: "2026-07-15",
          mobileRecordDate: null,
          scrollY: 0,
        },
      },
    });
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "23" } });
    fillBlankLedgerAmounts();
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("服务器暂时不可用，请稍后重试");
    expect(screen.getByLabelText("现金")).toHaveValue("23");
    expect(screen.getByLabelText("当前位置")).toHaveTextContent("/ledger?date=2026-07-15");
  });

  it("normalizes rest amounts and wash count while keeping activity notes", async () => {
    let body: any;
    render(<LedgerForm config={singleConfig} categories={[{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }]} onSave={(value) => { body = value; }} />);
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText("洗车数量"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("活动"), { target: { value: "设备检修" } });
    fireEvent.change(screen.getByLabelText("状态"), { target: { value: "休息" } });
    expect(screen.getByLabelText("活动")).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(body).toMatchObject({ is_open: "休息", wash_count: 0, activity: "设备检修", items: [{ category_id: 1, amount: 0 }] });
  });

  it("reports edits against the loaded snapshot and preserves collapsed values", async () => {
    const onDirtyChange = vi.fn();
    render(<LedgerForm config={singleConfig} categories={[{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }]} onSave={() => undefined} onDirtyChange={onDirtyChange} />);

    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    fireEvent.change(screen.getByLabelText("活动"), { target: { value: "夏日活动" } });
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    expect(screen.getByLabelText("活动")).toHaveValue("夏日活动");
  });

  it("keeps a manually selected weather value when delayed automatic weather arrives", async () => {
    const props = { config: singleConfig, categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], onSave: () => undefined };
    const view = render(<LedgerForm {...props} />);
    await chooseRecordWeather("中雨");
    view.rerender(<LedgerForm {...props} weather={{ weather: "晴", weather_code: 1, temperature_max: 20, temperature_min: 10, precipitation: 0 }} />);
    expect(screen.getByRole("combobox", { name: "天气" })).toHaveTextContent("中雨");
  });

  it("blocks decimal and negative amounts with a visible whole-number error", () => {
    const saves: unknown[] = [];
    render(<LedgerForm config={singleConfig} categories={[{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }]} onSave={(value) => saves.push(value)} />);
    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "12.3" } }); fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(screen.getByRole("alert")).toHaveTextContent("金额必须是大于等于 0 的整数");
    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "-1" } });
    expect(screen.getByText("合计 —")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(screen.getByRole("alert")).toHaveTextContent("金额必须是大于等于 0 的整数"); expect(saves).toHaveLength(0);
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
    server.use(http.get("/api/database/1/records", ({ request }) => { requested.push(new URL(request.url).search); return HttpResponse.json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 }); }));
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

    fillBlankLedgerAmounts();
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    const savedEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(savedEvent);
    expect(savedEvent.defaultPrevented).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /2026-07-13/ }));
    expect(screen.queryByRole("alertdialog", { name: "放弃未保存的修改？" })).not.toBeInTheDocument();
  });

  it("stays clean after an existing record is saved and refetched canonically", async () => {
    let saved = false;
    renderLedger([
      http.get("/api/ledger/1/:date", ({ params }) => params.date === "recent" ? HttpResponse.json([]) : HttpResponse.json(recordSnapshot(saved ? 13 : 12, saved ? "促销" : null))),
      http.put("/api/ledger/1/:date", async ({ request }) => {
        const body = await request.json() as any;
        expect(body.items[0].amount).toBe(13);
        expect(body.activity).toBe("促销");
        saved = true;
        return HttpResponse.json(recordSnapshot(13, "促销"));
      }),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "13" } });
    fireEvent.click(screen.getByRole("button", { name: "洗车数量 / 活动" }));
    fireEvent.change(screen.getByLabelText("活动"), { target: { value: " 促销 " } });
    fillBlankLedgerAmounts();
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
        return HttpResponse.json(recordSnapshot(10, null, "晴"));
      }),
      http.put("/api/ledger/1/:date", () => HttpResponse.json(recordSnapshot(10, null, "晴"))),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "10" } });
    fillBlankLedgerAmounts();
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    await waitFor(() => expect(recordCalls).toBe(2));

    await act(async () => { releaseWeather(); });
    await waitFor(() => expect(weatherReturned).toBe(true));
    expect(screen.getByRole("combobox", { name: "天气" })).toHaveTextContent("请选择天气");
    const intermediateEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(intermediateEvent);
    expect(intermediateEvent.defaultPrevented).toBe(false);

    await act(async () => { releaseRecord(); });
    await waitFor(() => expect(screen.getByRole("combobox", { name: "天气" })).toHaveTextContent("晴"));

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
        if (recordCalls === 1) return HttpResponse.json(recordSnapshot(5));
        return recordCalls === 2 ? HttpResponse.json({ detail: "failed" }, { status: 500 }) : HttpResponse.json(recordSnapshot(10, null, "晴"));
      }),
      http.put("/api/ledger/1/:date", () => HttpResponse.json(recordSnapshot(10))),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "10" } });
    fillBlankLedgerAmounts();
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
    await waitFor(() => expect(screen.getByRole("combobox", { name: "天气" })).toHaveTextContent("晴"));
  });

  it("keeps a newly created record retryable when its post-save refetch fails", async () => {
    let recordCalls = 0;
    renderLedger([
      http.get("/api/ledger/1/:date", ({ params }) => {
        if (params.date === "recent") return HttpResponse.json([]);
        recordCalls += 1;
        if (recordCalls === 1) return HttpResponse.json({ detail: "not found" }, { status: 404 });
        return recordCalls === 2 ? HttpResponse.json({ detail: "failed" }, { status: 500 }) : HttpResponse.json(recordSnapshot(10, null, "晴"));
      }),
      http.put("/api/ledger/1/:date", () => HttpResponse.json({ id: 9, date: "2026-07-15", daily_revenue: 10 })),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "10" } });
    fillBlankLedgerAmounts();
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    await waitFor(() => expect(recordCalls).toBe(2));

    expect(screen.getByLabelText("现金")).toHaveValue("10");
    expect(screen.getByRole("alert")).toHaveTextContent("台账刷新失败，请稍后重试");
    const savedEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(savedEvent);
    expect(savedEvent.defaultPrevented).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "重试台账" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "天气" })).toHaveTextContent("晴"));
    const canonicalEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(canonicalEvent);
    expect(canonicalEvent.defaultPrevented).toBe(false);
  });

  it("keeps edits made while a save is pending after success and record refetch", async () => {
    let release!: () => void;
    const delayed = new Promise<void>((resolve) => { release = resolve; });
    let saved = false;
    renderLedger([
      http.get("/api/ledger/1/:date", ({ params }) => params.date === "recent" ? HttpResponse.json([]) : saved ? HttpResponse.json(recordSnapshot(10)) : HttpResponse.json({ detail: "not found" }, { status: 404 })),
      http.put("/api/ledger/1/:date", async () => { await delayed; saved = true; return HttpResponse.json(recordSnapshot(10)); }),
    ]);
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "10" } });
    fillBlankLedgerAmounts();
    fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "20" } });
    release();
    expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
    await waitFor(() => expect(screen.getByLabelText("现金")).toHaveValue("20"));

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("binds save invalidation to the original store across a store switch", async () => {
    let release!: () => void; const delayed = new Promise<void>((resolve) => { release = resolve; }); let saveUrl = "";
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "One", timezone: "Europe/Berlin" }, { id: 2, name: "Two", timezone: "Europe/Berlin" }])),
      http.get("/api/income-config/:store/current", ({ params }) => HttpResponse.json({ ...singleConfig, store_id: Number(params.store), items: [{ ...singleConfig.items[0], store_id: Number(params.store) }] })),
      http.get("/api/database/:store/records", () => HttpResponse.json({ items: [], categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 })),
      http.get("/api/ledger/:store/recent", () => HttpResponse.json([])), http.get("/api/weather/:store/:date", () => HttpResponse.json({ weather: null })), http.get("/api/ledger/:store/:date", () => HttpResponse.json({ detail: "not found" }, { status: 404 })),
      http.put("/api/ledger/:store/:date", async ({ request }) => { saveUrl = request.url; await delayed; return HttpResponse.json({ id: 1, date: "2026-07-13", daily_revenue: 1 }); }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<MemoryRouter><QueryClientProvider client={client}><StoreProvider><StoreControls /><LedgerPage /></StoreProvider></QueryClientProvider></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "choose1" })); fireEvent.click(await screen.findByRole("button", { name: "选择台账日期：2026年7月15日" })); fireEvent.click(screen.getByRole("button", { name: "2026年7月13日" }));
    fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "1" } }); fillBlankLedgerAmounts(); fireEvent.click(screen.getByRole("button", { name: "补记历史记录" }));
    client.setQueryData(["dashboard", 1], true); client.setQueryData(["dashboard", 2], true); fireEvent.click(screen.getByRole("button", { name: "choose2" })); fireEvent.click(await screen.findByRole("button", { name: "放弃修改" })); release();
    await waitFor(() => expect(saveUrl).toContain("/api/ledger/1/2026-07-13")); expect(new URL(saveUrl).search).toBe(""); await waitFor(() => expect(client.getQueryState(["dashboard", 1])?.isInvalidated).toBe(true)); expect(client.getQueryState(["dashboard", 2])?.isInvalidated).toBe(false);
  });

  it("confirms before discarding edits when switching stores", async () => {
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "One", timezone: "Europe/Berlin" }, { id: 2, name: "Two", timezone: "Europe/Berlin" }])),
      http.get("/api/income-config/:store/current", ({ params }) => HttpResponse.json({ ...singleConfig, store_id: Number(params.store), items: [{ ...singleConfig.items[0], store_id: Number(params.store) }] })),
      http.get("/api/database/:store/records", () => HttpResponse.json({ items: [], categories: [{ id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 }], sum_daily_revenue: 0, total: 0, page: 1, page_size: 1 })),
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
    await waitFor(() => expect(screen.getByLabelText("现金")).toHaveValue(""));
  });

  it("shows a save error directly without an overwrite confirmation", async () => {
    server.use(http.put("/api/ledger/1/:date", () => HttpResponse.json({ detail: "exists" }, { status: 409 })));
    renderLedger();
    const saveButton = await screen.findByRole("button", { name: "保存今日记录" });
    fillBlankLedgerAmounts();
    fireEvent.click(saveButton);
    expect(await screen.findByRole("alert")).toHaveTextContent("数据已经发生变化，请刷新后重试");
    expect(screen.queryByText(/覆盖已有记录/)).not.toBeInTheDocument();
  });

  it("shows recent loading failures separately and retries them", async () => {
    let calls = 0;
    renderLedger([http.get("/api/ledger/1/recent", () => { calls += 1; return calls === 1 ? HttpResponse.json({ detail: "Recent unavailable" }, { status: 500 }) : HttpResponse.json([]); })]);
    expect(await screen.findByRole("alert")).toHaveTextContent("服务器暂时不可用，请稍后重试"); fireEvent.click(screen.getByRole("button", { name: "重试最近记录" })); await waitFor(() => expect(calls).toBe(2)); expect(screen.getByText("暂无记录")).toBeInTheDocument();
  });
});
