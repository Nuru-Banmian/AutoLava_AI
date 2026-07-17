import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import { IncomeItemsPanel } from "@/admin/IncomeItemsPanel";

const current = {
  store_id: 9,
  version_id: 3,
  version: 3,
  enabled: true,
  formula: "总收入 = 现金 + 刷卡",
  created_at: "2026-07-15T10:00:00",
  items: [
    { id: 31, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 0 },
    { id: 32, category_id: 2, name: "刷卡", include_in_total: true, is_active: true, sort_order: 1 },
    { id: 33, category_id: 3, name: "其他", include_in_total: false, is_active: true, sort_order: 2 },
  ],
};

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPanel(onDirtyChange = vi.fn(), storeId = 9) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { onDirtyChange, ...render(
    <QueryClientProvider client={client}>
      <IncomeItemsPanel storeId={storeId} onDirtyChange={onDirtyChange} />
    </QueryClientProvider>,
  ) };
}

type CategoryFixture = { id: number; store_id: number; name: string; include_in_total: boolean; is_active: boolean; sort_order: number; archived_at: string | null };

function mockReads(categories: CategoryFixture[] = [
  { id: 1, store_id: 9, name: "现金", include_in_total: true, is_active: true, sort_order: 0, archived_at: null },
  { id: 2, store_id: 9, name: "刷卡", include_in_total: true, is_active: true, sort_order: 1, archived_at: null },
  { id: 3, store_id: 9, name: "其他", include_in_total: false, is_active: true, sort_order: 2, archived_at: null },
]) {
  server.use(
    http.get("/api/income-config/9/current", () => HttpResponse.json(current)),
    http.get("/api/admin/income-categories", () => HttpResponse.json(categories)),
  );
}

describe("IncomeItemsPanel", () => {
  it("keeps edits local, previews the formula, reindexes moves, and publishes once", async () => {
    let publishCount = 0;
    let published: unknown;
    mockReads();
    server.use(http.put("/api/admin/stores/9/income-config", async ({ request }) => {
      publishCount += 1;
      published = await request.json();
      return HttpResponse.json(current);
    }));
    const user = userEvent.setup();
    const dirty = vi.fn();
    renderPanel(dirty);

    expect(screen.queryByLabelText("收入项目门店")).not.toBeInTheDocument();
    expect(await screen.findByText("营业额 = 现金 + 刷卡；“其他”只记录，不计入营业额")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "计入营业额 其他" }));
    expect(dirty).toHaveBeenLastCalledWith(true);
    expect(screen.getByText("营业额 = 现金 + 刷卡 + 其他")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "上移 其他" }));
    const otherName = screen.getByRole("textbox", { name: "项目名称 其他" });
    await user.clear(otherName);
    await user.type(otherName, "线上支付");
    await user.type(screen.getByRole("textbox", { name: "新收入项目名称" }), "洗车卡");
    await user.click(screen.getByRole("button", { name: "添加收入项目" }));

    expect(publishCount).toBe(0);
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(publishCount).toBe(1));
    await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
    expect(published).toEqual({
      enabled: true,
      items: [
        { category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 0 },
        { category_id: 3, name: "线上支付", include_in_total: true, is_active: true, sort_order: 1 },
        { category_id: 2, name: "刷卡", include_in_total: true, is_active: true, sort_order: 2 },
        { category_id: null, name: "洗车卡", include_in_total: true, is_active: true, sort_order: 3 },
      ],
    });
  });

  it("archives and restores categories and explains why referenced categories cannot be deleted", async () => {
    const categories = [
      { id: 1, store_id: 9, name: "现金", include_in_total: true, is_active: true, sort_order: 0, archived_at: null },
      { id: 7, store_id: 9, name: "旧项目", include_in_total: false, is_active: false, sort_order: 4, archived_at: "2026-07-15T11:00:00" },
    ];
    mockReads(categories);
    let archived = 0;
    let restored = 0;
    server.use(
      http.post("/api/admin/income-categories/1/archive", () => { archived += 1; return HttpResponse.json({ ...categories[0], archived_at: "2026-07-16T10:00:00", is_active: false }); }),
      http.post("/api/admin/income-categories/7/restore", () => { restored += 1; return HttpResponse.json({ ...categories[1], archived_at: null }); }),
      http.delete("/api/admin/income-categories/7", () => HttpResponse.json({ detail: "此收入项目已有历史记录，只能归档，不能永久删除" }, { status: 409 })),
    );
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel();

    await screen.findByText("旧项目");
    await user.click(screen.getByRole("button", { name: "归档 现金" }));
    await waitFor(() => expect(archived).toBe(1));
    await user.click(screen.getByRole("button", { name: "恢复 旧项目" }));
    await waitFor(() => expect(restored).toBe(1));
    await user.click(screen.getByRole("button", { name: "永久删除 旧项目" }));
    expect(confirm).toHaveBeenCalledWith("永久删除后无法恢复，确定删除“旧项目”吗？");
    expect(await screen.findByRole("alert")).toHaveTextContent("此收入项目已有历史记录，只能归档，不能永久删除");
  });

  it("clears the previous store draft while the newly selected store is loading", async () => {
    let release!: () => void;
    const loading = new Promise<void>((resolve) => { release = resolve; });
    server.use(
      http.get("/api/income-config/9/current", () => HttpResponse.json(current)),
      http.get("/api/income-config/10/current", async () => { await loading; return HttpResponse.json({ ...current, store_id: 10, version_id: null, version: 0, enabled: false, items: [] }); }),
      http.get("/api/admin/income-categories", () => HttpResponse.json([])),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    function Harness() {
      const [storeId, setStoreId] = useState(9);
      return <><button type="button" onClick={() => setStoreId(10)}>外部切换门店</button><IncomeItemsPanel storeId={storeId} onDirtyChange={() => undefined} /></>;
    }
    const user = userEvent.setup();
    render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>);

    await screen.findByRole("textbox", { name: "项目名称 现金" });
    await user.click(screen.getByRole("button", { name: "外部切换门店" }));
    expect(screen.queryByRole("textbox", { name: "项目名称 现金" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
    release();
    await waitFor(() => expect(screen.queryByText("正在加载收入项目…")).not.toBeInTheDocument());
  });

  it("preserves a disabled non-empty configuration when publishing edits", async () => {
    const disabled = { ...current, enabled: false };
    let published: { enabled?: boolean } | undefined;
    server.use(
      http.get("/api/income-config/9/current", () => HttpResponse.json(disabled)),
      http.get("/api/admin/income-categories", () => HttpResponse.json([])),
      http.put("/api/admin/stores/9/income-config", async ({ request }) => {
        published = await request.json() as { enabled: boolean };
        return HttpResponse.json(disabled);
      }),
    );
    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByRole("checkbox", { name: "启用收入项目明细" })).not.toBeChecked();
    const name = await screen.findByRole("textbox", { name: "项目名称 现金" });
    await user.clear(name);
    await user.type(name, "现金收款");
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(published?.enabled).toBe(false));
  });

  it("keeps unrelated unsaved draft edits after archiving an item", async () => {
    let configReads = 0;
    const afterArchive = { ...current, version_id: 4, version: 4, items: [current.items[0], current.items[1]] };
    mockReads();
    server.use(
      http.get("/api/income-config/9/current", () => HttpResponse.json(configReads++ === 0 ? current : afterArchive)),
      http.post("/api/admin/income-categories/3/archive", () => HttpResponse.json({ id: 3, store_id: 9, name: "其他", include_in_total: false, is_active: false, sort_order: 2, archived_at: "2026-07-16T12:00:00" })),
    );
    const user = userEvent.setup();
    renderPanel();

    const cash = await screen.findByRole("textbox", { name: "项目名称 现金" });
    await user.clear(cash);
    await user.type(cash, "现金收款");
    await user.click(screen.getByRole("button", { name: "归档 其他" }));

    await waitFor(() => expect(configReads).toBeGreaterThan(1));
    expect(screen.getByDisplayValue("现金收款")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "项目名称 其他" })).not.toBeInTheDocument();
  });

  it("locks draft controls during publish and hides a stale error after an external store switch", async () => {
    let reject!: () => void;
    const pending = new Promise<void>((resolve) => { reject = resolve; });
    server.use(
      http.get("/api/income-config/9/current", () => HttpResponse.json(current)),
      http.get("/api/income-config/10/current", () => HttpResponse.json({ ...current, store_id: 10, version_id: null, version: 0, enabled: false, items: [] })),
      http.get("/api/admin/income-categories", () => HttpResponse.json([])),
      http.put("/api/admin/stores/9/income-config", async () => { await pending; return HttpResponse.json({ detail: "旧门店保存失败" }, { status: 500 }); }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    function Harness() {
      const [storeId, setStoreId] = useState(9);
      return <><button type="button" onClick={() => setStoreId(10)}>外部切换门店</button><IncomeItemsPanel storeId={storeId} onDirtyChange={() => undefined} /></>;
    }
    const user = userEvent.setup();
    render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>);

    await screen.findByRole("textbox", { name: "项目名称 现金" });
    await user.click(screen.getByRole("button", { name: "保存" }));
    expect(screen.getByRole("textbox", { name: "项目名称 现金" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "计入营业额 现金" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "添加收入项目" })).toBeDisabled();
    expect(screen.queryByLabelText("收入项目门店")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "外部切换门店" }));
    reject();
    await screen.findByText("营业额 = 0");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
