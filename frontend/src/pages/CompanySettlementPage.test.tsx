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
  it("confirms the whole record after an explicit prompt and refreshes its month", async () => {
    let submitted: unknown;
    let current = record();
    renderPage([
      http.get("/api/settlements/1/months/:month", () => HttpResponse.json({
        ...monthResponse([current]),
        confirmed_settlement_income: current.status === "confirmed" ? current.amount : 0,
        pending_amount: current.status === "pending" ? current.amount : 0,
        monthly_total: current.status === "confirmed" ? 1020 : 900,
      })),
      http.post("/api/settlements/1/records/20/confirm", async ({ request }) => {
        submitted = await request.json();
        current = record({ status: "confirmed", revision: 2 });
        return HttpResponse.json(current);
      }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "确认Alpha开票记录到账" }));
    expect(screen.getByRole("alertdialog", { name: "确认整笔到账？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认到账" }));

    await waitFor(() => expect(submitted).toEqual({ revision: 1 }));
    expect(await screen.findByRole("status")).toHaveTextContent("开票记录已确认到账");
    expect(await screen.findByRole("button", { name: "撤销Alpha开票记录到账确认" })).toBeInTheDocument();
    expect(screen.getByText("€120", { selector: "dd" })).toBeInTheDocument();
  });

  it("adopts an already-confirmed canonical state after a concurrent confirmation", async () => {
    let current = record();
    renderPage([
      http.get("/api/settlements/1/months/:month", () => HttpResponse.json(monthResponse([current]))),
      http.post("/api/settlements/1/records/20/confirm", () => {
        current = record({ status: "confirmed", revision: 2 });
        return HttpResponse.json({
          detail: {
            code: "settlement_record_state_conflict",
            message: "开票记录已经确认到账",
            current_record: current,
          },
        }, { status: 409 });
      }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "确认Alpha开票记录到账" }));
    fireEvent.click(screen.getByRole("button", { name: "确认到账" }));

    expect(await screen.findByRole("status")).toHaveTextContent("记录状态已同步：已确认到账");
    expect(screen.queryByRole("alertdialog", { name: "确认整笔到账？" })).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "撤销Alpha开票记录到账确认" })).toBeInTheDocument();
  });

  it("keeps a failed revocation open for a safe retry", async () => {
    let requests = 0;
    let current = record({ status: "confirmed", revision: 2 });
    renderPage([
      http.get("/api/settlements/1/months/:month", () => HttpResponse.json(monthResponse([current]))),
      http.post("/api/settlements/1/records/20/revoke-confirmation", () => {
        requests += 1;
        if (requests === 1) {
          return HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 });
        }
        current = record({ status: "pending", revision: 3 });
        return HttpResponse.json(current);
      }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "撤销Alpha开票记录到账确认" }));
    expect(screen.getByRole("alertdialog", { name: "撤销到账确认？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认撤销到账确认" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("服务器暂时不可用，请稍后重试");

    fireEvent.click(screen.getByRole("button", { name: "确认撤销到账确认" }));
    await waitFor(() => expect(requests).toBe(2));
    expect(await screen.findByRole("status")).toHaveTextContent("已撤销开票记录到账确认");
    expect(await screen.findByRole("button", { name: "编辑Alpha开票记录" })).toBeInTheDocument();
  });

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

  it("adopts the canonical revision after an edit conflict while preserving the draft", async () => {
    const submitted: unknown[] = [];
    renderPage([
      http.patch("/api/settlements/1/records/20", async ({ request }) => {
        const body = await request.json();
        submitted.push(body);
        if (submitted.length === 1) {
          return HttpResponse.json({
            detail: {
              code: "settlement_record_revision_conflict",
              message: "开票记录已被其他用户修改，请重新加载后再试",
              current_record: record({ amount: 200, revision: 2 }),
            },
          }, { status: 409 });
        }
        return HttpResponse.json(record({ amount: 250, revision: 3 }));
      }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "编辑Alpha开票记录" }));
    fireEvent.change(screen.getByLabelText("编辑金额（整数欧元）"), { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "保存开票记录修改" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("开票记录已被其他用户修改");
    expect(screen.getByLabelText("编辑金额（整数欧元）")).toHaveValue(250);
    fireEvent.click(screen.getByRole("button", { name: "重试修改" }));

    await waitFor(() => expect(submitted).toEqual([
      { company_id: 10, amount: 250, revision: 1 },
      { company_id: 10, amount: 250, revision: 2 },
    ]));
    expect(await screen.findByRole("status")).toHaveTextContent("开票记录已修改");
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

  it("adopts the canonical revision before retrying a conflicted deletion", async () => {
    const submitted: unknown[] = [];
    renderPage([
      http.delete("/api/settlements/1/records/20", async ({ request }) => {
        submitted.push(await request.json());
        if (submitted.length === 1) {
          return HttpResponse.json({
            detail: {
              code: "settlement_record_revision_conflict",
              message: "开票记录已被其他用户修改，请重新加载后再试",
              current_record: record({ amount: 200, revision: 2 }),
            },
          }, { status: 409 });
        }
        return new HttpResponse(null, { status: 204 });
      }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: "删除Alpha开票记录" }));
    fireEvent.click(screen.getByRole("button", { name: "确认永久删除开票记录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("开票记录已被其他用户修改");
    fireEvent.click(screen.getByRole("button", { name: "确认永久删除开票记录" }));

    await waitFor(() => expect(submitted).toEqual([{ revision: 1 }, { revision: 2 }]));
    expect(await screen.findByRole("status")).toHaveTextContent("开票记录已永久删除");
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
