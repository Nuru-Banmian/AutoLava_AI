import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { CompanySettlementPage } from "@/pages/CompanySettlementPage";
import { StoreProvider, useStore } from "@/stores/StoreProvider";

const server = setupServer();

const companies = [
  { id: 10, name: "Alpha", is_active: true },
  { id: 11, name: "Beta", is_active: true },
];

function record(overrides: Record<string, unknown> = {}) {
  return {
    id: 20,
    company_id: 10,
    company_name: "Alpha",
    opening_month: "2026-07",
    amount: 120,
    status: "pending",
    revision: 1,
    created_at: "2026-07-10T08:00:00",
    ...overrides,
  };
}

function monthResponse(records = [record()]) {
  return {
    opening_month: "2026-07",
    records,
    daily_ledger_revenue: 900,
    confirmed_settlement_income: 0,
    pending_amount: records.reduce((total, item) => total + Number(item.amount), 0),
    monthly_total: 900,
  };
}

function StoreControls() {
  const { select } = useStore();
  return <button onClick={() => select(2)}>切换到Roma</button>;
}

function renderPage(extra: Parameters<typeof server.use> = []) {
  server.use(
    ...extra,
    http.get("/api/stores/accessible", () => HttpResponse.json([
      { id: 1, name: "Berlin", timezone: "Europe/Berlin", company_settlement_enabled: true },
      { id: 2, name: "Roma", timezone: "Europe/Rome", company_settlement_enabled: true },
    ])),
    http.get("/api/settlements/:storeId", ({ params }) => HttpResponse.json({
      store_id: Number(params.storeId),
      store_name: params.storeId === "1" ? "Berlin" : "Roma",
      company_settlement_enabled: true,
    })),
    http.get("/api/settlements/:storeId/companies", ({ request }) =>
      HttpResponse.json(new URL(request.url).searchParams.has("archived") ? [] : companies)),
    http.get("/api/settlements/:storeId/months/:month", ({ params }) =>
      HttpResponse.json(monthResponse(params.storeId === "1" ? [record()] : []))),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <StoreProvider userId={1}>
          <StoreControls />
          <CompanySettlementPage />
        </StoreProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-07-21T10:00:00Z"));
});
afterEach(() => {
  localStorage.clear();
  server.resetHandlers();
  vi.useRealTimers();
});
afterAll(() => server.close());

describe("CompanySettlementPage record corrections", () => {
  it("edits a pending record with its revision and keeps its opening month", async () => {
    let submitted: unknown;
    let current = record();
    renderPage([
      http.get("/api/settlements/1/months/:month", () => HttpResponse.json(monthResponse([current]))),
      http.patch("/api/settlements/1/records/20", async ({ request }) => {
        submitted = await request.json();
        current = record({ company_id: 11, company_name: "Beta", amount: 250, revision: 2 });
        return HttpResponse.json(current);
      }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "编辑Alpha开票记录" }));
    fireEvent.change(screen.getByLabelText("编辑结算公司"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("编辑金额（整数欧元）"), { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "保存开票记录修改" }));

    await waitFor(() => expect(submitted).toEqual({ company_id: 11, amount: 250, revision: 1 }));
    expect(await screen.findByRole("status")).toHaveTextContent("开票记录已修改");
    expect(await screen.findByRole("button", { name: "编辑Beta开票记录" })).toBeInTheDocument();
    expect(screen.getByLabelText("开票月份")).toHaveValue("2026-07");
  });

  it("keeps the edit draft open and retryable when saving fails", async () => {
    let requests = 0;
    renderPage([
      http.patch("/api/settlements/1/records/20", () => {
        requests += 1;
        return HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 });
      }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "编辑Alpha开票记录" }));
    fireEvent.change(screen.getByLabelText("编辑金额（整数欧元）"), { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "保存开票记录修改" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("服务器暂时不可用，请稍后重试");
    expect(screen.getByLabelText("编辑金额（整数欧元）")).toHaveValue(250);
    fireEvent.click(screen.getByRole("button", { name: "重试修改" }));
    await waitFor(() => expect(requests).toBe(2));
  });

  it("permanently deletes only after confirmation and sends the current revision", async () => {
    let submitted: unknown;
    let deleted = false;
    renderPage([
      http.get("/api/settlements/1/months/:month", () =>
        HttpResponse.json(monthResponse(deleted ? [] : [record()]))),
      http.delete("/api/settlements/1/records/20", async ({ request }) => {
        submitted = await request.json();
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "删除Alpha开票记录" }));
    expect(screen.getByRole("alertdialog", { name: "永久删除开票记录？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认永久删除开票记录" }));

    await waitFor(() => expect(submitted).toEqual({ revision: 1 }));
    expect(await screen.findByRole("status")).toHaveTextContent("开票记录已永久删除");
    expect(await screen.findByText("本月暂无开票记录。")).toBeInTheDocument();
  });

  it("clears the old store month, edit dialog, errors, and mutation state when switching stores", async () => {
    renderPage([
      http.patch("/api/settlements/1/records/20", () =>
        HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 })),
    ]);

    fireEvent.change(await screen.findByLabelText("开票月份"), { target: { value: "2026-06" } });
    fireEvent.click(await screen.findByRole("button", { name: "编辑Alpha开票记录" }));
    fireEvent.change(screen.getByLabelText("编辑金额（整数欧元）"), { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "保存开票记录修改" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    fireEvent.click(screen.getByText("切换到Roma"));

    expect(await screen.findByText("Roma的公司结算")).toBeInTheDocument();
    expect(screen.getByLabelText("开票月份")).toHaveValue("2026-07");
    expect(screen.queryByRole("dialog", { name: "修改开票记录" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
