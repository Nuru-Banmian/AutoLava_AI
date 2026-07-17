import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";

import { StoreWorkspace } from "@/admin/StoreWorkspace";
import { UnsavedChangesProvider } from "@/navigation/UnsavedChanges";
import { accessibleStoresKey } from "@/stores/StoreProvider";

vi.mock("@/components/StoreLocationPicker", () => ({
  StoreLocationPicker: ({ value, onConfirm, buttonLabel }: {
    value: unknown;
    onConfirm: (location: unknown) => void;
    buttonLabel?: string;
  }) => <button type="button" onClick={() => onConfirm({
    label: "Via Nuova",
    latitude: 45.46,
    longitude: 9.19,
    timezone: "Europe/Rome",
  })}>{buttonLabel ?? (value ? "修改地图位置" : "打开地图选择")}</button>,
}));

const roma = { id: 9, name: "Roma", address: "Roma Centro", latitude: "41.9", longitude: "12.5", timezone: "Europe/Rome", is_active: true };
const milano = { id: 10, name: "Milano", address: "Milano Centro", latitude: "45.4", longitude: "9.2", timezone: "Europe/Rome", is_active: true };
const romaIncome = {
  store_id: 9,
  version_id: 3,
  version: 3,
  enabled: true,
  formula: "营业额 = 现金",
  created_at: "2026-07-17T07:00:00Z",
  items: [{ id: 31, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 0 }],
};
const milanoIncome = {
  store_id: 10,
  version_id: 2,
  version: 2,
  enabled: true,
  formula: "营业额 = 刷卡",
  created_at: "2026-07-17T07:00:00Z",
  items: [{ id: 32, category_id: 2, name: "刷卡", include_in_total: true, is_active: true, sort_order: 0 }],
};
const publishedIncomeConfig = {
  store_id: 9,
  version_id: 4,
  version: 4,
  enabled: true,
  formula: "营业额 = 现金",
  created_at: "2026-07-17T08:00:00Z",
  items: [{ id: 41, category_id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 0 }],
};

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});
afterAll(() => server.close());

interface WorkspaceHandlers {
  stores?: typeof roma[];
  patchStore?: () => Response | Promise<Response>;
  publishIncome?: () => Response | Promise<Response>;
  deleteStore?: () => Response | Promise<Response>;
  onStoreRead?: () => void;
}

function mockStoreWorkspace({
  stores = [roma],
  patchStore = () => HttpResponse.json(roma),
  publishIncome = () => HttpResponse.json(publishedIncomeConfig),
  deleteStore = () => new HttpResponse(null, { status: 204 }),
  onStoreRead = () => undefined,
}: WorkspaceHandlers = {}) {
  server.use(
    http.get("/api/admin/stores", () => {
      onStoreRead();
      return HttpResponse.json(stores);
    }),
    http.get("/api/income-config/:storeId/current", ({ params }) => HttpResponse.json(Number(params.storeId) === 9 ? romaIncome : milanoIncome)),
    http.get("/api/admin/income-categories", ({ request }) => {
      const storeId = Number(new URL(request.url).searchParams.get("store_id"));
      return HttpResponse.json(storeId === 9
        ? [{ id: 1, store_id: 9, name: "现金", include_in_total: true, is_active: true, sort_order: 0, archived_at: null }]
        : [{ id: 2, store_id: 10, name: "刷卡", include_in_total: true, is_active: true, sort_order: 0, archived_at: null }]);
    }),
    http.patch("/api/admin/stores/9", patchStore),
    http.put("/api/admin/stores/9/income-config", publishIncome),
    http.delete("/api/admin/stores/9", deleteStore),
  );
}

function renderWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { client, ...render(
    <QueryClientProvider client={client}>
      <UnsavedChangesProvider><StoreWorkspace /></UnsavedChangesProvider>
    </QueryClientProvider>,
  ) };
}

function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}

it("selects the first store on initial load and renders income before details", async () => {
  mockStoreWorkspace({ stores: [roma, milano] });
  renderWorkspace();

  expect(await screen.findByLabelText("门店名称 Roma")).toBeInTheDocument();
  const income = screen.getByRole("region", { name: "收入项目" });
  const details = screen.getByRole("region", { name: "门店资料" });
  expect(income.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING)
    .toBeTruthy();

  const selector = screen.getByRole("combobox", { name: "门店" });
  expect(selector).toHaveValue("9");
  expect(within(selector).queryByRole("option", { name: "请选择门店" }))
    .not.toBeInTheDocument();
  expect(screen.queryByText("请选择门店")).not.toBeInTheDocument();
});

it("keeps the store selector blank in create mode without a selectable prompt", async () => {
  mockStoreWorkspace({ stores: [roma] });
  renderWorkspace();
  await screen.findByLabelText("门店名称 Roma");

  await userEvent.click(screen.getByRole("button", { name: "新建门店" }));

  expect(screen.getByRole("combobox", { name: "门店" })).toHaveValue("");
  expect(screen.queryByRole("option", { name: "请选择门店" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("门店名称")).toBeInTheDocument();
});

it("does not invent a store selection for an empty list", async () => {
  mockStoreWorkspace({ stores: [] });
  renderWorkspace();

  const selector = await screen.findByRole("combobox", { name: "门店" });
  expect(selector).toHaveValue("");
  expect(screen.queryByText("请选择门店")).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "门店资料" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "收入项目" })).not.toBeInTheDocument();
});

it("selects a newly created store", async () => {
  let stores = [roma];
  mockStoreWorkspace();
  server.use(
    http.get("/api/admin/stores", () => HttpResponse.json(stores)),
    http.post("/api/admin/stores", () => {
      stores = [roma, milano];
      return HttpResponse.json(milano, { status: 201 });
    }),
  );
  renderWorkspace();
  await screen.findByLabelText("门店名称 Roma");
  await userEvent.click(screen.getByRole("button", { name: "新建门店" }));
  await userEvent.type(screen.getByLabelText("门店名称"), "Milano");
  await userEvent.click(screen.getByRole("button", { name: "打开地图选择" }));
  await userEvent.click(screen.getByRole("button", { name: "添加门店" }));

  expect(await screen.findByLabelText("门店名称 Milano")).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "门店" })).toHaveValue("10");
});

it("uses one store selection for independent details and income cards", async () => {
  mockStoreWorkspace();
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));

  expect(screen.getByRole("heading", { name: "门店资料" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "收入项目" })).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "门店资料" })).getByRole("button", { name: "保存" })).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "收入项目" })).getByRole("button", { name: "保存" })).toBeInTheDocument();
  expect(screen.getAllByLabelText("门店")).toHaveLength(1);
});

it("guards store switches when the details card is dirty", async () => {
  mockStoreWorkspace({ stores: [roma, milano] });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.clear(screen.getByLabelText("门店名称 Roma"));
  await userEvent.type(screen.getByLabelText("门店名称 Roma"), "Roma Centro");
  await userEvent.click(screen.getByRole("button", { name: /Milano/ }));

  expect(screen.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
  expect(await screen.findByLabelText("门店名称 Milano")).toBeInTheDocument();
});

it("guards store switches when the income card is dirty", async () => {
  mockStoreWorkspace({ stores: [roma, milano] });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.click(await screen.findByRole("checkbox", { name: "计入营业额 现金" }));
  await userEvent.click(screen.getByRole("button", { name: /Milano/ }));

  expect(screen.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "继续编辑" }));
  expect(screen.getByLabelText("门店名称 Roma")).toBeInTheDocument();
});

it("keeps store and income saves independent when one request fails", async () => {
  let incomePublished = false;
  mockStoreWorkspace({
    patchStore: () => HttpResponse.json({ detail: "门店保存失败" }, { status: 500 }),
    publishIncome: () => {
      incomePublished = true;
      return HttpResponse.json(publishedIncomeConfig);
    },
  });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.click(within(screen.getByRole("region", { name: "门店资料" })).getByRole("button", { name: "保存" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("门店保存失败");

  await userEvent.click(within(screen.getByRole("region", { name: "收入项目" })).getByRole("button", { name: "保存" }));
  await waitFor(() => expect(incomePublished).toBe(true));
  expect(screen.getByRole("alert")).toHaveTextContent("门店保存失败");
});

it("refreshes Roma after a stale success without replacing the newer Milano drafts", async () => {
  const pending = deferredResponse();
  let storeReads = 0;
  mockStoreWorkspace({ stores: [roma, milano], patchStore: () => pending.promise, onStoreRead: () => { storeReads += 1; } });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.clear(screen.getByLabelText("门店名称 Roma"));
  await userEvent.type(screen.getByLabelText("门店名称 Roma"), "Roma Draft");
  await userEvent.click(within(screen.getByRole("region", { name: "门店资料" })).getByRole("button", { name: "保存" }));
  await userEvent.click(screen.getByRole("button", { name: /Milano/ }));
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
  const milanoName = await screen.findByLabelText("门店名称 Milano");
  await userEvent.clear(milanoName);
  await userEvent.type(milanoName, "Milano Draft");
  await userEvent.click(await screen.findByRole("checkbox", { name: "计入营业额 刷卡" }));

  pending.resolve(HttpResponse.json({ ...roma, name: "Roma Draft" }));

  await waitFor(() => expect(storeReads).toBeGreaterThan(1));
  expect(screen.getByDisplayValue("Milano Draft")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "计入营业额 刷卡" })).not.toBeChecked();
  expect(screen.queryByLabelText("门店名称 Roma Draft")).not.toBeInTheDocument();
});

it("does not render a stale Roma save error in the Milano cards", async () => {
  const pending = deferredResponse();
  mockStoreWorkspace({ stores: [roma, milano], patchStore: () => pending.promise });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.clear(screen.getByLabelText("门店名称 Roma"));
  await userEvent.type(screen.getByLabelText("门店名称 Roma"), "Roma Draft");
  await userEvent.click(within(screen.getByRole("region", { name: "门店资料" })).getByRole("button", { name: "保存" }));
  await userEvent.click(screen.getByRole("button", { name: /Milano/ }));
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
  await screen.findByLabelText("门店名称 Milano");

  pending.resolve(HttpResponse.json({ detail: "旧门店保存失败" }, { status: 500 }));

  await waitFor(() => expect(screen.queryByText("旧门店保存失败")).not.toBeInTheDocument());
  expect(screen.getByLabelText("门店名称 Milano")).toBeInTheDocument();
});

it("keeps an unsaved details draft guarded after changing store activity", async () => {
  let lifecycleCalls = 0;
  mockStoreWorkspace({
    stores: [roma, milano],
    patchStore: () => {
      lifecycleCalls += 1;
      return HttpResponse.json({ ...roma, is_active: false });
    },
  });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  const name = screen.getByLabelText("门店名称 Roma");
  await userEvent.clear(name);
  await userEvent.type(name, "Roma Draft");
  await userEvent.click(screen.getByRole("button", { name: "修改位置" }));
  await userEvent.click(screen.getByRole("button", { name: "停用门店 Roma" }));
  await waitFor(() => expect(lifecycleCalls).toBe(1));

  await userEvent.click(screen.getByRole("button", { name: /Milano/ }));

  expect(screen.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "继续编辑" }));
  expect(screen.getByDisplayValue("Roma Draft")).toBeInTheDocument();
  expect(screen.getByText("Via Nuova")).toBeInTheDocument();
});

it("keeps both card save labels exact while their requests are pending", async () => {
  const detailsPending = deferredResponse();
  const incomePending = deferredResponse();
  mockStoreWorkspace({
    patchStore: () => detailsPending.promise,
    publishIncome: () => incomePending.promise,
  });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  const details = screen.getByRole("region", { name: "门店资料" });
  const income = screen.getByRole("region", { name: "收入项目" });

  await userEvent.click(within(details).getByRole("button", { name: "保存" }));
  await userEvent.click(within(income).getByRole("button", { name: "保存" }));

  expect(within(details).getByRole("button", { name: "保存" })).toBeDisabled();
  expect(within(income).getByRole("button", { name: "保存" })).toBeDisabled();
  expect(within(details).queryByRole("button", { name: "保存中…" })).not.toBeInTheDocument();
  expect(within(income).queryByRole("button", { name: "保存中…" })).not.toBeInTheDocument();

  detailsPending.resolve(HttpResponse.json(roma));
  incomePending.resolve(HttpResponse.json(publishedIncomeConfig));
  await waitFor(() => expect(within(details).getByRole("button", { name: "保存" })).not.toBeDisabled());
  await waitFor(() => expect(within(income).getByRole("button", { name: "保存" })).not.toBeDisabled());
});

it("keeps lifecycle controls and explains a referenced-store delete conflict", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mockStoreWorkspace({ deleteStore: () => HttpResponse.json({ detail: "已有历史记录" }, { status: 409 }) });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  const danger = screen.getByRole("region", { name: "危险操作" });

  expect(within(danger).getByRole("button", { name: "停用门店 Roma" })).toBeInTheDocument();
  await userEvent.click(within(danger).getByRole("button", { name: "永久删除门店 Roma" }));

  expect(window.confirm).toHaveBeenCalledWith("确定永久删除门店“Roma”吗？只有从未使用的门店可以删除。");
  expect(await screen.findByRole("alert")).toHaveTextContent("已有经营或历史记录，只能停用门店");
});

it("invalidates store lists and selects the first remaining store after deletion", async () => {
  let stores = [roma, milano];
  vi.spyOn(window, "confirm").mockReturnValue(true);
  server.use(
    http.get("/api/admin/stores", () => HttpResponse.json(stores)),
    http.get("/api/income-config/:storeId/current", ({ params }) => HttpResponse.json(Number(params.storeId) === 9 ? romaIncome : milanoIncome)),
    http.get("/api/admin/income-categories", () => HttpResponse.json([])),
    http.delete("/api/admin/stores/9", () => {
      stores = [milano];
      return new HttpResponse(null, { status: 204 });
    }),
  );
  const { client } = renderWorkspace();
  client.setQueryData(accessibleStoresKey, [roma, milano]);
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.click(screen.getByRole("button", { name: "永久删除门店 Roma" }));

  expect(await screen.findByLabelText("门店名称 Milano")).toBeInTheDocument();
  expect(client.getQueryState(accessibleStoresKey)?.isInvalidated).toBe(true);
});

it("guards a dirty income draft before permanently deleting the selected store", async () => {
  let stores = [roma, milano];
  let deleteCalls = 0;
  vi.spyOn(window, "confirm").mockReturnValue(true);
  server.use(
    http.get("/api/admin/stores", () => HttpResponse.json(stores)),
    http.get("/api/income-config/:storeId/current", ({ params }) => HttpResponse.json(Number(params.storeId) === 9 ? romaIncome : milanoIncome)),
    http.get("/api/admin/income-categories", () => HttpResponse.json([])),
    http.delete("/api/admin/stores/9", () => {
      deleteCalls += 1;
      stores = [milano];
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.click(await screen.findByRole("checkbox", { name: "计入营业额 现金" }));

  await userEvent.click(screen.getByRole("button", { name: "永久删除门店 Roma" }));

  expect(screen.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
  expect(deleteCalls).toBe(0);
  await userEvent.click(screen.getByRole("button", { name: "继续编辑" }));
  expect(screen.getByLabelText("门店名称 Roma")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "计入营业额 现金" })).not.toBeChecked();
  expect(deleteCalls).toBe(0);

  await userEvent.click(screen.getByRole("button", { name: "永久删除门店 Roma" }));
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
  expect(await screen.findByLabelText("门店名称 Milano")).toBeInTheDocument();
  expect(deleteCalls).toBe(1);
});

it("reasserts a dirty income draft after a current delete is rejected", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mockStoreWorkspace({
    stores: [roma, milano],
    deleteStore: () => HttpResponse.json({ detail: "已有历史记录" }, { status: 409 }),
  });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.click(await screen.findByRole("checkbox", { name: "计入营业额 现金" }));

  await userEvent.click(screen.getByRole("button", { name: "永久删除门店 Roma" }));
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("已有经营或历史记录，只能停用门店");
  expect(screen.getByRole("checkbox", { name: "计入营业额 现金" })).not.toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: /Milano/ }));

  expect(screen.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "继续编辑" }));
  expect(screen.getByLabelText("门店名称 Roma")).toBeInTheDocument();
});

it("does not reassert a stale rejected delete for another store selection", async () => {
  const pending = deferredResponse();
  let deleteStarted = false;
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mockStoreWorkspace({
    stores: [roma, milano],
    deleteStore: () => {
      deleteStarted = true;
      return pending.promise;
    },
  });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.click(await screen.findByRole("checkbox", { name: "计入营业额 现金" }));
  await userEvent.click(screen.getByRole("button", { name: "永久删除门店 Roma" }));
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
  await waitFor(() => expect(deleteStarted).toBe(true));

  await userEvent.click(screen.getByRole("button", { name: /Milano/ }));
  expect(await screen.findByLabelText("门店名称 Milano")).toBeInTheDocument();
  await act(async () => {
    pending.resolve(HttpResponse.json({ detail: "旧门店删除失败" }, { status: 409 }));
    await pending.promise;
  });

  await userEvent.click(screen.getByRole("button", { name: /Roma/ }));
  expect(screen.queryByRole("alertdialog", { name: "放弃未保存的修改？" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("门店名称 Roma")).toBeInTheDocument();
});

it("does not reassert a clean income draft when a current pending delete is rejected", async () => {
  const deletePending = deferredResponse();
  let deleteStarted = false;
  let publishCalls = 0;
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mockStoreWorkspace({
    stores: [roma, milano],
    deleteStore: () => {
      deleteStarted = true;
      return deletePending.promise;
    },
    publishIncome: () => {
      publishCalls += 1;
      return HttpResponse.json(publishedIncomeConfig);
    },
  });
  renderWorkspace();
  await userEvent.click(await screen.findByRole("button", { name: /Roma/ }));
  await userEvent.click(await screen.findByRole("checkbox", { name: "计入营业额 现金" }));
  await userEvent.click(screen.getByRole("button", { name: "永久删除门店 Roma" }));
  await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
  await waitFor(() => expect(deleteStarted).toBe(true));

  const income = screen.getByRole("region", { name: "收入项目" });
  await userEvent.click(within(income).getByRole("button", { name: "保存" }));
  await waitFor(() => expect(publishCalls).toBe(1));
  await waitFor(() => expect(within(income).getByRole("button", { name: "保存" })).not.toBeDisabled());
  expect(screen.getByRole("checkbox", { name: "计入营业额 现金" })).toBeChecked();

  await act(async () => {
    deletePending.resolve(HttpResponse.json({ detail: "已有历史记录" }, { status: 409 }));
    await deletePending.promise;
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("已有经营或历史记录，只能停用门店");
  await userEvent.click(screen.getByRole("button", { name: /Milano/ }));

  expect(screen.queryByRole("alertdialog", { name: "放弃未保存的修改？" })).not.toBeInTheDocument();
  expect(await screen.findByLabelText("门店名称 Milano")).toBeInTheDocument();
});
