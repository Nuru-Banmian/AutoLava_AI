import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ChartsPage } from "@/pages/ChartsPage";
import { StoreProvider } from "@/stores/StoreProvider";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function response(categories = [
  { category_id: 1, category_name: "现金", amount: "200.00" },
  { category_id: 2, category_name: "刷卡", amount: "150.00" },
]) {
  return {
    kpis: {
      total_revenue: "350.00",
      record_days: 2,
      open_days: 1,
      average_revenue: "350.00",
      primary_categories: [],
      total_wash_count: 5,
      average_ticket: "70.00",
    },
    daily: [
      { date: "2026-07-12", revenue: "150.00" },
      { date: "2026-07-13", revenue: "200.00" },
    ],
    categories,
    monthly: [{ month: "2026-07", revenue: "350.00" }],
    weather: [{ weather: "晴", average_revenue: "350.00" }],
    weekday: [{ weekday: 0, average_revenue: "350.00" }],
  };
}

function renderPage(categories?: ReturnType<typeof response>["categories"]) {
  server.use(
    http.get("/api/stores/accessible", () =>
      HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }]),
    ),
    http.get("/api/charts/1", () => HttpResponse.json(response(categories))),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StoreProvider><ChartsPage /></StoreProvider>
    </QueryClientProvider>,
  );
}

describe("ChartsPage", () => {
  it("offers only approved ranges and focused revenue panels", async () => {
    renderPage();

    expect(await screen.findByRole("button", { name: "最近 7 天" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "本月" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "自定义日期" })).toBeInTheDocument();
    expect(await screen.findByText("总营业额")).toBeInTheDocument();
    expect(screen.getByText("营业天数")).toBeInTheDocument();
    expect(screen.getByText("平均营业额")).toBeInTheDocument();
    expect(screen.getByText("营业额趋势")).toBeInTheDocument();
    expect(screen.getByText("收入构成")).toBeInTheDocument();

    for (const removed of ["天气表现", "星期表现", "月度趋势", "洗车总数", "平均客单价", "主要收入分类"]) {
      expect(screen.queryByText(removed)).not.toBeInTheDocument();
    }
  });

  it("hides composition when only one category exists", async () => {
    renderPage([{ category_id: 1, category_name: "现金", amount: "350.00" }]);

    expect(await screen.findByText("营业额趋势")).toBeInTheDocument();
    expect(screen.queryByText("收入构成")).not.toBeInTheDocument();
  });

  it("switches between preset and custom date ranges", async () => {
    const urls: URL[] = [];
    server.use(
      http.get("/api/stores/accessible", () =>
        HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }]),
      ),
      http.get("/api/charts/1", ({ request }) => {
        urls.push(new URL(request.url));
        return HttpResponse.json(response());
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><StoreProvider><ChartsPage /></StoreProvider></QueryClientProvider>);

    await screen.findByText("总营业额");
    fireEvent.click(screen.getByRole("button", { name: "最近 7 天" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "最近 7 天" })).toHaveAttribute("aria-pressed", "true"));
    fireEvent.click(screen.getByRole("button", { name: "自定义日期" }));
    fireEvent.change(screen.getByLabelText("图表开始日期"), { target: { value: "2026-06-01" } });
    fireEvent.change(screen.getByLabelText("图表结束日期"), { target: { value: "2026-06-30" } });

    await waitFor(() => expect(urls.some((url) =>
      url.searchParams.get("start") === "2026-06-01" && url.searchParams.get("end") === "2026-06-30",
    )).toBe(true));
  });

  it("keeps large decimal KPI strings exact", async () => {
    const large = response();
    large.kpis.total_revenue = "9007199254740993.10";
    large.kpis.average_revenue = "9007199254740993.10";
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }])),
      http.get("/api/charts/1", () => HttpResponse.json(large)),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><StoreProvider><ChartsPage /></StoreProvider></QueryClientProvider>);

    expect(await screen.findAllByText("€9007199254740993.10")).toHaveLength(2);
  });
});
