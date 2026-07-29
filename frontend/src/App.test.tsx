import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { buttonVariants } from "./components/ui/button";
import App, { Application } from "./App";
import { monthInTimezone } from "./pages/CompanySettlementPage";
import { createAppRouter } from "./router";

const applicationStyles = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

const server = setupServer(
  http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "admin", role: "admin", is_owner: false })),
  http.get("/api/stores/accessible", () => HttpResponse.json([
    { id: 1, name: "总店", timezone: "Europe/Berlin" },
    { id: 2, name: "二店", timezone: "Europe/Berlin" },
  ])),
  http.get("/api/admin/stores", () => HttpResponse.json([])),
  http.get("/api/agent/stores/:storeId", () => HttpResponse.json(
    { detail: "数据分析 Agent 未启用" },
    { status: 403 },
  )),
  http.get("/api/agent/stores/:storeId/conversation", ({ params }) => HttpResponse.json({
    conversation_id: 1,
    store_id: Number(params.storeId),
    store_name: "总店",
    messages: [],
  })),
  http.get("/api/dashboard/:storeId", () => HttpResponse.json([])),
  http.get("/api/settlements/:storeId/months/:month", ({ params }) => HttpResponse.json({
    opening_month: params.month,
    records: [],
    daily_ledger_revenue: 0,
    confirmed_settlement_income: 0,
    pending_amount: 0,
    monthly_total: 0,
  })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

type TestIdentity = "regular-user" | "administrator" | "final-administrator";

function renderApplication(path: string, identity?: TestIdentity) {
  if (identity) {
    const isFinalAdministrator = identity === "final-administrator";
    const role = identity === "regular-user" ? "user" : "admin";
    server.use(http.get("/api/auth/me", () => HttpResponse.json({
      id: 1,
      username: isFinalAdministrator ? "final-admin" : role,
      role,
      is_owner: isFinalAdministrator,
    })));
  }
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createAppRouter([path]);
  return { ...render(<Application queryClient={queryClient} router={router} />), router };
}

function themeTokens() {
  const root = applicationStyles.match(/:root\s*\{([^}]*)\}/)?.[1];
  if (!root) throw new Error("index.css is missing its :root theme block");
  return Object.fromEntries(
    [...root.matchAll(/--([\w-]+):\s*([^;]+);/g)].map(([, name, value]) => [name, value.trim()]),
  );
}

function oklchRelativeLuminance(value: string) {
  const match = value.match(/^oklch\(([\d.]+)\s+([\d.]+)\s+([\d.]+)\)$/);
  if (!match) throw new Error(`Expected an opaque OKLCH color, received ${value}`);
  const [, lightness, chroma, hue] = match.map(Number);
  const hueRadians = hue * Math.PI / 180;
  const a = chroma * Math.cos(hueRadians);
  const b = chroma * Math.sin(hueRadians);
  const l = lightness + 0.3963377774 * a + 0.2158037573 * b;
  const m = lightness - 0.1055613458 * a - 0.0638541728 * b;
  const s = lightness - 0.0894841775 * a - 1.291485548 * b;
  const linearRed = 4.0767416621 * l ** 3 - 3.3077115913 * m ** 3 + 0.2309699292 * s ** 3;
  const linearGreen = -1.2684380046 * l ** 3 + 2.6097574011 * m ** 3 - 0.3413193965 * s ** 3;
  const linearBlue = -0.0041960863 * l ** 3 - 0.7034186147 * m ** 3 + 1.707614701 * s ** 3;
  return 0.2126 * Math.min(1, Math.max(0, linearRed))
    + 0.7152 * Math.min(1, Math.max(0, linearGreen))
    + 0.0722 * Math.min(1, Math.max(0, linearBlue));
}

function contrastRatio(first: string, second: string) {
  const luminances = [oklchRelativeLuminance(first), oklchRelativeLuminance(second)].sort((a, b) => b - a);
  return (luminances[0] + 0.05) / (luminances[1] + 0.05);
}

describe("App", () => {
  it("loads the shared application shell", async () => {
    renderApplication("/");
    expect(await screen.findByText("AutoLava AI")).toBeInTheDocument();
  });

  it("keeps the retired charts route unmatched without mounting either legacy page", () => {
    const router = createAppRouter(["/charts"]);

    expect(router.state.errors).toBeDefined();
    expect(Object.values(router.state.errors ?? {})).toEqual(expect.arrayContaining([
      expect.objectContaining({ status: 404, statusText: "Not Found" }),
    ]));
    expect(router.state.matches.map((match) => match.route.path)).not.toContain("charts");
  });

  it("shows four mobile entries and hides management from regular users", async () => {
    renderApplication("/more", "regular-user");
    const nav = await screen.findByRole("navigation", { name: "移动导航" });
    expect(within(nav).getAllByRole("link")).toHaveLength(4);
    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual(["首页", "记账", "记录", "更多"]);
    expect(nav).toHaveClass("grid-cols-4");
    const more = screen.getByRole("navigation", { name: "更多功能" });
    expect(within(more).queryByRole("link", { name: "经营分析" })).not.toBeInTheDocument();
    expect(within(more).queryByRole("combobox", { name: "门店" })).not.toBeInTheDocument();
    expect(within(more).getByRole("link", { name: "修改密码" })).toBeInTheDocument();
    expect(screen.queryByText("管理中心")).not.toBeInTheDocument();
    expect(screen.queryByText("系统状态")).not.toBeInTheDocument();
  });

  it("lets a maximum-length store name shrink inside the shell picker", async () => {
    const storeName = "超".repeat(120);
    server.use(http.get("/api/stores/accessible", () => HttpResponse.json([
      { id: 1, name: storeName, timezone: "Europe/Berlin" },
    ])));
    renderApplication("/more", "regular-user");

    const desktopPicker = await screen.findByTestId("desktop-store-picker");
    const select = within(desktopPicker).getByRole("combobox", { name: "门店" });
    expect(await within(select).findByRole("option", { name: storeName })).toBeInTheDocument();
    expect(select).toHaveClass("min-w-0", "max-w-full", "flex-1");
    expect(select.closest("label")).toHaveClass("min-w-0", "max-w-full");
    expect(select.closest("label")?.parentElement).toHaveClass("min-w-0", "max-w-full");
    expect(select.closest("label")?.parentElement?.parentElement).toHaveClass("min-w-0", "max-w-full");
  });

  it("moves the global store selector out of More and into the shell", async () => {
    renderApplication("/more", "regular-user");
    const more = await screen.findByRole("navigation", { name: "更多功能" });
    expect(within(more).queryByRole("combobox", { name: "门店" })).not.toBeInTheDocument();
    expect(await screen.findAllByRole("combobox", { name: "门店" })).toHaveLength(2);

    const brand = screen.getByText("AutoLava AI");
    const desktopPicker = screen.getByTestId("desktop-store-picker");
    const mobilePicker = screen.getByTestId("mobile-store-picker");
    expect(brand.compareDocumentPosition(desktopPicker) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(mobilePicker.parentElement).toContain(brand);
  });

  it("hides global store context in admin and restores it after leaving", async () => {
    const view = renderApplication("/admin", "administrator");
    await screen.findByRole("heading", { name: "系统管理" });
    expect(screen.queryByTestId("desktop-store-picker")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mobile-store-picker")).not.toBeInTheDocument();
    expect(screen.queryByText("门店加载失败，请重试")).not.toBeInTheDocument();
    await view.router.navigate("/");
    const desktopPicker = await screen.findByTestId("desktop-store-picker");
    expect(await within(desktopPicker).findByRole("option", { name: "总店" })).toBeInTheDocument();
    expect(screen.getAllByRole("combobox", { name: "门店" })).toHaveLength(2);
  });

  it("shows management and system status in More for administrators", async () => {
    renderApplication("/more", "administrator");
    const more = await screen.findByRole("navigation", { name: "更多功能" });
    expect(within(more).getByRole("link", { name: "管理中心" })).toHaveAttribute("href", "/admin");
    expect(within(more).getByRole("link", { name: "系统状态" })).toHaveAttribute("href", "/admin?tab=status");
  });

  it("keeps the administrator desktop sidebar in the required order", async () => {
    renderApplication("/", "administrator");
    const nav = await screen.findByRole("navigation", { name: "主导航" });
    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "首页",
      "记账",
      "营业记录",
      "管理中心",
    ]);
  });

  it("shows the Agent entry only when the current store backend gate allows it", async () => {
    server.use(http.get("/api/agent/stores/1", () => HttpResponse.json({
      store_id: 1,
      store_name: "总店",
    })));
    renderApplication("/", "administrator");

    const desktop = await screen.findByRole("navigation", { name: "主导航" });
    expect(await within(desktop).findByRole("link", { name: "数据分析 Agent" })).toHaveAttribute("href", "/agent");
  });

  it("opens the enabled Agent page for the selected store", async () => {
    server.use(http.get("/api/agent/stores/1", () => HttpResponse.json({
      store_id: 1,
      store_name: "总店",
    })));
    renderApplication("/agent", "administrator");

    expect(await screen.findByRole("heading", { name: "数据分析 Agent" })).toBeInTheDocument();
    const currentStoreLabel = await screen.findByText("Agent 当前门店");
    expect(currentStoreLabel.nextElementSibling).toHaveTextContent("总店");
  });

  it("restores, sends, and resets the current store Agent conversation", async () => {
    let savedMessages = [
      { id: 1, role: "user", content: "上个月经营怎么样？", created_at: "2026-07-29T08:00:00" },
      { id: 2, role: "assistant", content: "上个月营业额保持稳定。", created_at: "2026-07-29T08:00:01" },
    ];
    server.use(
      http.get("/api/agent/stores/1", () => HttpResponse.json({
        store_id: 1,
        store_name: "总店",
      })),
      http.get("/api/agent/stores/1/conversation", () => HttpResponse.json({
        conversation_id: 9,
        store_id: 1,
        store_name: "总店",
        messages: savedMessages,
        latest_turn: null,
      })),
      http.post("/api/agent/stores/1/messages", async ({ request }) => {
        const body = await request.json() as { content: string };
        savedMessages = [
          ...savedMessages,
          { id: 3, role: "user", content: body.content, created_at: "2026-07-29T09:00:00" },
          { id: 4, role: "assistant", content: "本月目前有 12 个经营日。", created_at: "2026-07-29T09:00:01" },
        ];
        return new HttpResponse([
          '{"type":"started","turn_id":7}',
          '{"type":"phase","turn_id":7,"phase":"preparing_answer"}',
          '{"type":"answer_delta","turn_id":7,"delta":"本月目前有 12 个经营日。"}',
          '{"type":"completed","turn_id":7}',
          "",
        ].join("\n"), {
          headers: { "content-type": "application/x-ndjson" },
        });
      }),
      http.delete("/api/agent/stores/1/conversation", () => new HttpResponse(null, { status: 204 })),
    );
    renderApplication("/agent", "administrator");

    expect(await screen.findByText("上个月营业额保持稳定。")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "向 Agent 提问" }), "本月有几个经营日？");
    await userEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("本月目前有 12 个经营日。")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "重置会话" }));
    await userEvent.click(screen.getByRole("button", { name: "确认重置" }));
    await waitFor(() => expect(screen.queryByText("上个月营业额保持稳定。")).not.toBeInTheDocument());
    expect(screen.getByText("还没有消息，可以从当前门店的经营问题开始。")).toBeInTheDocument();
  });

  it("polls a running Agent turn after the JSON Lines connection closes early", async () => {
    let conversationReads = 0;
    server.use(
      http.get("/api/agent/stores/1", () => HttpResponse.json({
        store_id: 1,
        store_name: "总店",
      })),
      http.get("/api/agent/stores/1/conversation", () => {
        conversationReads += 1;
        if (conversationReads === 1) {
          return HttpResponse.json({
            conversation_id: 9,
            store_id: 1,
            store_name: "总店",
            messages: [],
            latest_turn: null,
          });
        }
        if (conversationReads === 2) {
          return HttpResponse.json({
            conversation_id: 9,
            store_id: 1,
            store_name: "总店",
            messages: [
              { id: 3, role: "user", content: "分析营业额", created_at: "2026-07-29T09:00:00" },
            ],
            latest_turn: {
              id: 7,
              status: "running",
              error_message: null,
              started_at: "2026-07-29T09:00:00",
              finished_at: null,
            },
          });
        }
        return HttpResponse.json({
          conversation_id: 9,
          store_id: 1,
          store_name: "总店",
          messages: [
            { id: 3, role: "user", content: "分析营业额", created_at: "2026-07-29T09:00:00" },
            { id: 4, role: "assistant", content: "后台完成的回答", created_at: "2026-07-29T09:00:02" },
          ],
          latest_turn: {
            id: 7,
            status: "completed",
            error_message: null,
            started_at: "2026-07-29T09:00:00",
            finished_at: "2026-07-29T09:00:02",
          },
        });
      }),
      http.post("/api/agent/stores/1/messages", () => new HttpResponse(
        '{"type":"started","turn_id":7}\n',
        { headers: { "content-type": "application/x-ndjson" } },
      )),
    );
    renderApplication("/agent", "administrator");

    await userEvent.type(
      await screen.findByRole("textbox", { name: "向 Agent 提问" }),
      "分析营业额",
    );
    await userEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "实时连接已断开，后台仍会继续处理",
    );
    expect(await screen.findByText("后台完成的回答", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(conversationReads).toBeGreaterThanOrEqual(3);
  });

  it("does not mount the Agent page for an ordinary store user", async () => {
    renderApplication("/agent", "regular-user");

    await waitFor(() => expect(screen.getByRole("heading", { name: "仪表盘" })).toBeInTheDocument());
    expect(screen.queryByRole("heading", { name: "数据分析 Agent" })).not.toBeInTheDocument();
  });

  it("shows company settlement in the enabled store only and keeps mobile bottom navigation stable", async () => {
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([
        { id: 1, name: "已启用", timezone: "Europe/Rome", company_settlement_enabled: true },
        { id: 2, name: "未启用", timezone: "Europe/Rome", company_settlement_enabled: false },
      ])),
      http.get("/api/settlements/1", () => HttpResponse.json({ store_id: 1, store_name: "已启用", company_settlement_enabled: true })),
    );
    renderApplication("/more", "regular-user");

    const desktop = await screen.findByRole("navigation", { name: "主导航" });
    const desktopStorePicker = within(screen.getByTestId("desktop-store-picker")).getByRole("combobox", { name: "门店" });
    await within(desktopStorePicker).findByRole("option", { name: "已启用" });
    await userEvent.selectOptions(desktopStorePicker, "1");
    await waitFor(() => expect(within(desktop).getByRole("link", { name: "公司结算" })).toBeInTheDocument());
    expect(within(desktop).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "首页", "记账", "营业记录", "公司结算",
    ]);
    const mobile = screen.getByRole("navigation", { name: "移动导航" });
    expect(within(mobile).getAllByRole("link")).toHaveLength(4);
    expect(within(screen.getByRole("navigation", { name: "更多功能" })).getByRole("link", { name: "公司结算" })).toBeInTheDocument();

    await userEvent.selectOptions(
      desktopStorePicker,
      "2",
    );
    await waitFor(() => expect(within(desktop).queryByRole("link", { name: "公司结算" })).not.toBeInTheDocument());
    expect(within(screen.getByRole("navigation", { name: "更多功能" })).queryByRole("link", { name: "公司结算" })).not.toBeInTheDocument();
  });

  it.each([
    ["普通用户", "regular-user" as const],
    ["管理员", "administrator" as const],
    ["最终管理员", "final-administrator" as const],
  ])("%s can open the enabled store settlement route and read its data", async (_identity, identity) => {
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([
        { id: 1, name: "共享门店", timezone: "Europe/Rome", company_settlement_enabled: true },
      ])),
      http.get("/api/settlements/1", () => HttpResponse.json({
        store_id: 1,
        store_name: "共享门店",
        company_settlement_enabled: true,
      })),
      http.get("/api/settlements/1/companies", ({ request }) => HttpResponse.json(
        new URL(request.url).searchParams.has("archived")
          ? []
          : [{ id: 10, name: "共享车队", is_active: true }],
      )),
      http.get("/api/settlements/1/months/:month", ({ params }) => HttpResponse.json({
        opening_month: params.month,
        records: [{
          id: 20,
          company_id: 10,
          company_name: "共享车队",
          opening_month: params.month,
          amount: 420,
          status: "confirmed",
          revision: 1,
          created_at: "2026-07-10T08:00:00",
        }],
        daily_ledger_revenue: 900,
        confirmed_settlement_income: 420,
        pending_amount: 0,
        monthly_total: 1320,
      })),
    );
    renderApplication("/settlements", identity);

    const desktop = await screen.findByRole("navigation", { name: "主导航" });
    await waitFor(() => {
      expect(within(desktop).getByRole("link", { name: "公司结算" })).toBeInTheDocument();
    });
    expect(await screen.findByRole("heading", { name: "公司结算" })).toBeInTheDocument();
    expect(await screen.findByLabelText("开票月份")).toBeInTheDocument();
    expect((await screen.findAllByText("€420")).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "结算公司管理" }));
    expect(await screen.findByRole("button", { name: "共享车队更多操作" })).toBeInTheDocument();
  });

  it("rejects a direct company settlement visit for a disabled store", async () => {
    renderApplication("/settlements", "regular-user");

    expect(await screen.findByRole("alert")).toHaveTextContent("当前门店未启用公司结算");
    expect(screen.getByRole("link", { name: "返回首页" })).toHaveAttribute("href", "/");
  });

  it("offers an accessible retry when the settlement gate read fails", async () => {
    let reads = 0;
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([
        { id: 1, name: "已启用", timezone: "Europe/Rome", company_settlement_enabled: true },
      ])),
      http.get("/api/settlements/1", () => {
        reads += 1;
        return reads === 1
          ? HttpResponse.json({ detail: "暂时失败" }, { status: 503 })
          : HttpResponse.json({ store_id: 1, store_name: "已启用", company_settlement_enabled: true });
      }),
      http.get("/api/settlements/1/companies", () => HttpResponse.json([])),
    );
    renderApplication("/settlements", "regular-user");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("暂时失败"));
    await userEvent.click(screen.getByRole("button", { name: "重试公司结算" }));

    expect(await screen.findByRole("heading", { name: "公司结算" })).toBeInTheDocument();
    expect(reads).toBe(2);
  });

  it("maintains the company directory and preserves a failed inline name for retry", async () => {
    let creates = 0;
    const active = [{ id: 1, name: "Alpha Fleet", is_active: true }];
    const archived = [{ id: 2, name: "Old Fleet", is_active: false }];
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([
        { id: 1, name: "已启用", timezone: "Europe/Rome", company_settlement_enabled: true },
      ])),
      http.get("/api/settlements/1", () => HttpResponse.json({ store_id: 1, store_name: "已启用", company_settlement_enabled: true })),
      http.get("/api/settlements/1/companies", ({ request }) => HttpResponse.json(
        new URL(request.url).searchParams.get("archived") === "true" ? archived : active,
      )),
      http.post("/api/settlements/1/companies", async ({ request }) => {
        creates += 1;
        const body = await request.json() as { name: string };
        if (creates === 1) return HttpResponse.json({ detail: "暂时无法保存" }, { status: 503 });
        const company = { id: 3, name: body.name.trim().replace(/\s+/g, " "), is_active: true };
        active.push(company);
        return HttpResponse.json(company, { status: 201 });
      }),
      http.post("/api/settlements/1/companies/1/archive", () => {
        const [company] = active.splice(0, 1);
        company.is_active = false;
        archived.push(company);
        return HttpResponse.json(company);
      }),
    );
    renderApplication("/settlements", "regular-user");

    await userEvent.click(await screen.findByRole("button", { name: "结算公司管理" }));
    expect(await screen.findByRole("button", { name: "Alpha Fleet更多操作" })).toBeInTheDocument();
    expect(screen.queryByText("Old Fleet")).not.toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: "新结算公司名称" });
    await userEvent.type(input, "  New   Fleet  ");
    await userEvent.click(screen.getByRole("button", { name: "新增结算公司" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法保存");
    expect(input).toHaveValue("  New   Fleet  ");

    await userEvent.click(screen.getByRole("button", { name: "重试操作" }));
    await waitFor(() => expect(input).toHaveValue(""));
    expect(screen.queryByText("操作成功")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "New Fleet更多操作" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Alpha Fleet更多操作" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "归档Alpha Fleet" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Alpha Fleet更多操作" })).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole("tab", { name: "已归档（2）" }));
    expect(await screen.findByText("Old Fleet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Alpha Fleet更多操作" }));
    expect(screen.getByRole("menuitem", { name: "恢复Alpha Fleet" })).toBeInTheDocument();

    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await userEvent.click(screen.getByRole("tab", { name: "使用中（1）" }));
    await userEvent.click(screen.getByRole("button", { name: "New Fleet更多操作" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "永久删除New Fleet" }));
    expect(confirm).toHaveBeenCalledWith("确定永久删除结算公司“New Fleet”吗？此操作无法撤销。");
    confirm.mockRestore();
  });

  it("clears company editing state on store switch and ignores the old store response", async () => {
    let creates = 0;
    let resolveOldRequest: (() => void) | undefined;
    const oldRequest = new Promise<void>((resolve) => { resolveOldRequest = resolve; });
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([
        { id: 1, name: "一店", timezone: "Europe/Rome", company_settlement_enabled: true },
        { id: 2, name: "二店", timezone: "Europe/Rome", company_settlement_enabled: true },
      ])),
      http.get("/api/settlements/:storeId", ({ params }) => HttpResponse.json({
        store_id: Number(params.storeId),
        store_name: params.storeId === "1" ? "一店" : "二店",
        company_settlement_enabled: true,
      })),
      http.get("/api/settlements/:storeId/companies", ({ params, request }) => {
        if (new URL(request.url).searchParams.get("archived") === "true") return HttpResponse.json([]);
        return HttpResponse.json(params.storeId === "1"
          ? [{ id: 1, name: "一店公司", is_active: true }]
          : [{ id: 2, name: "二店公司", is_active: true }]);
      }),
      http.post("/api/settlements/1/companies", async () => {
        creates += 1;
        if (creates === 1) return HttpResponse.json({ detail: "一店保存失败" }, { status: 503 });
        await oldRequest;
        return HttpResponse.json({ id: 3, name: "一店草稿", is_active: true }, { status: 201 });
      }),
    );
    renderApplication("/settlements", "regular-user");

    await userEvent.click(await screen.findByRole("button", { name: "结算公司管理" }));
    expect(await screen.findByRole("button", { name: "一店公司更多操作" })).toBeInTheDocument();
    const draft = screen.getByRole("textbox", { name: "新结算公司名称" });
    await userEvent.type(draft, "一店草稿");
    await userEvent.click(screen.getByRole("button", { name: "新增结算公司" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("一店保存失败");
    await userEvent.click(screen.getByRole("button", { name: "一店公司更多操作" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "重命名一店公司" }));
    expect(screen.getByRole("textbox", { name: "重命名一店公司" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "重试操作" }));

    const picker = within(screen.getByTestId("desktop-store-picker")).getByRole("combobox", { name: "门店" });
    await userEvent.selectOptions(picker, "2");
    await userEvent.click(await screen.findByRole("button", { name: "结算公司管理" }));
    expect(await screen.findByRole("button", { name: "二店公司更多操作" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "新结算公司名称" })).toHaveValue("");
    expect(screen.queryByRole("textbox", { name: "重命名一店公司" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重试操作" })).not.toBeInTheDocument();

    resolveOldRequest?.();
    await waitFor(() => expect(creates).toBe(2));
    expect(screen.queryByText("操作成功")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "二店公司更多操作" })).toBeInTheDocument();
  });

  it("uses the store timezone for the opening month boundary", () => {
    expect(monthInTimezone("Pacific/Honolulu", new Date("2026-08-01T01:00:00Z"))).toBe("2026-07");
    expect(monthInTimezone("Pacific/Kiritimati", new Date("2026-07-31T12:00:00Z"))).toBe("2026-08");
  });

  it("registers and summarizes a month while preserving a failed record for retry", async () => {
    let saves = 0;
    let created = false;
    const companies = [{ id: 1, name: "Alpha Fleet", is_active: true }];
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([
        { id: 1, name: "月结门店", timezone: "Pacific/Honolulu", company_settlement_enabled: true },
      ])),
      http.get("/api/settlements/1", () => HttpResponse.json({ store_id: 1, store_name: "月结门店", company_settlement_enabled: true })),
      http.get("/api/settlements/1/companies", ({ request }) => HttpResponse.json(
        new URL(request.url).searchParams.get("archived") === "true" ? [] : companies,
      )),
      http.post("/api/settlements/1/companies", async ({ request }) => {
        const body = await request.json() as { name: string };
        const company = { id: 2, name: body.name, is_active: true };
        companies.push(company);
        return HttpResponse.json(company, { status: 201 });
      }),
      http.get("/api/settlements/1/months/:month", ({ params }) => HttpResponse.json({
        opening_month: params.month,
        records: created ? [{ id: 7, company_id: 2, company_name: "Beta Fleet", opening_month: params.month, amount: 250, status: "pending", revision: 1, created_at: "2026-07-01T00:00:00" }] : [],
        daily_ledger_revenue: 1000,
        confirmed_settlement_income: 0,
        pending_amount: created ? 250 : 0,
        monthly_total: 1000,
      })),
      http.post("/api/settlements/1/records", async () => {
        saves += 1;
        if (saves === 1) return HttpResponse.json({ detail: "暂时无法登记" }, { status: 503 });
        created = true;
        return HttpResponse.json({ id: 7, company_id: 2, company_name: "Beta Fleet", opening_month: "2026-07", amount: 250, status: "pending", revision: 1, created_at: "2026-07-01T00:00:00" }, { status: 201 });
      }),
    );
    renderApplication("/settlements", "regular-user");

    const monthInput = await screen.findByLabelText("开票月份");
    expect(monthInput).toHaveValue(monthInTimezone("Pacific/Honolulu"));
    await waitFor(() => expect(screen.getByText("日常营业额").nextElementSibling).toHaveTextContent("€1,000"));
    expect(screen.getByText("月度总收入").nextElementSibling).toHaveTextContent("€1,000");

    await userEvent.click(screen.getByRole("button", { name: "结算公司管理" }));
    await userEvent.type(screen.getByRole("textbox", { name: "新结算公司名称" }), "Beta Fleet");
    await userEvent.click(screen.getByRole("button", { name: "新增结算公司" }));
    const companyInput = screen.getByRole("combobox", { name: "结算公司" });
    await within(companyInput).findByRole("option", { name: "Beta Fleet" });
    await userEvent.selectOptions(companyInput, "2");
    const amountInput = screen.getByRole("spinbutton", { name: "金额（整数欧元）" });
    await userEvent.type(amountInput, "250");
    await userEvent.click(screen.getByRole("button", { name: "登记待到账记录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法登记");
    expect(monthInput).toHaveValue(monthInTimezone("Pacific/Honolulu"));
    expect(screen.getByRole("combobox", { name: "结算公司" })).toHaveValue("2");
    expect(amountInput).toHaveValue(250);

    await userEvent.click(screen.getByRole("button", { name: "重试保存" }));
    await waitFor(() => expect(amountInput).toHaveValue(null));
    expect(within(await screen.findByRole("list", { name: `${monthInTimezone("Pacific/Honolulu")}开票记录` })).getByText("Beta Fleet")).toBeInTheDocument();
    expect(screen.getByText("待到账金额").nextElementSibling).toHaveTextContent("€250");
    expect(screen.getByText("月度总收入").nextElementSibling).toHaveTextContent("€1,000");
    expect(saves).toBe(2);
  });

  it("clears record drafts and errors when the store changes", async () => {
    let saves = 0;
    let oldSaveCompleted = false;
    let releaseOldSave: (() => void) | undefined;
    const oldSave = new Promise<void>((resolve) => { releaseOldSave = resolve; });
    server.use(
      http.get("/api/stores/accessible", () => HttpResponse.json([
        { id: 1, name: "一店", timezone: "Europe/Rome", company_settlement_enabled: true },
        { id: 2, name: "二店", timezone: "Pacific/Honolulu", company_settlement_enabled: true },
      ])),
      http.get("/api/settlements/:storeId", ({ params }) => HttpResponse.json({ store_id: Number(params.storeId), store_name: `${params.storeId === "1" ? "一" : "二"}店`, company_settlement_enabled: true })),
      http.get("/api/settlements/:storeId/companies", ({ params, request }) => HttpResponse.json(
        new URL(request.url).searchParams.get("archived") === "true" ? [] : [{ id: Number(params.storeId), name: `${params.storeId}号公司`, is_active: true }],
      )),
      http.get("/api/settlements/:storeId/months/:month", ({ params }) => HttpResponse.json({
        opening_month: params.month, records: [], daily_ledger_revenue: params.storeId === "1" ? 100 : 200,
        confirmed_settlement_income: 0, pending_amount: 0, monthly_total: params.storeId === "1" ? 100 : 200,
      })),
      http.post("/api/settlements/1/records", async () => {
        saves += 1;
        if (saves === 1) return HttpResponse.json({ detail: "一店保存失败" }, { status: 503 });
        await oldSave;
        oldSaveCompleted = true;
        return HttpResponse.json({ id: 9, company_id: 1, company_name: "1号公司", opening_month: "2026-06", amount: 88, status: "pending", revision: 1, created_at: "2026-06-01T00:00:00" }, { status: 201 });
      }),
    );
    renderApplication("/settlements", "regular-user");
    const company = await screen.findByRole("combobox", { name: "结算公司" });
    await within(company).findByRole("option", { name: "1号公司" });
    await userEvent.selectOptions(company, "1");
    await userEvent.clear(screen.getByLabelText("开票月份"));
    await userEvent.type(screen.getByLabelText("开票月份"), "2026-06");
    await userEvent.type(screen.getByRole("spinbutton", { name: "金额（整数欧元）" }), "88");
    await userEvent.click(screen.getByRole("button", { name: "登记待到账记录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("一店保存失败");
    await userEvent.click(screen.getByRole("button", { name: "重试保存" }));

    await userEvent.selectOptions(within(screen.getByTestId("desktop-store-picker")).getByRole("combobox", { name: "门店" }), "2");
    await waitFor(() => expect(screen.getByRole("combobox", { name: "结算公司" })).toHaveValue(""));
    expect(screen.getByLabelText("开票月份")).toHaveValue(monthInTimezone("Pacific/Honolulu"));
    expect(screen.getByRole("spinbutton", { name: "金额（整数欧元）" })).toHaveValue(null);
    expect(screen.queryByRole("button", { name: "重试保存" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("日常营业额").nextElementSibling).toHaveTextContent("€200"));
    releaseOldSave?.();
    await waitFor(() => expect(oldSaveCompleted).toBe(true));
    expect(screen.getByText("日常营业额").nextElementSibling).toHaveTextContent("€200");
    expect(screen.queryByRole("button", { name: "重试保存" })).not.toBeInTheDocument();
  });

  it("loads the approved blue theme tokens from index.css", () => {
    expect(themeTokens()).toMatchObject({
      radius: "0.875rem",
      background: "oklch(0.985 0.006 250)",
      foreground: "oklch(0.24 0.03 255)",
      card: "oklch(1 0 0)",
      "card-foreground": "oklch(0.24 0.03 255)",
      popover: "oklch(1 0 0)",
      "popover-foreground": "oklch(0.24 0.03 255)",
      primary: "oklch(0.55 0.19 255)",
      "primary-foreground": "oklch(0.99 0 0)",
      "primary-hover": "oklch(0.48 0.17 255)",
      "primary-active": "oklch(0.43 0.16 255)",
      secondary: "oklch(0.95 0.018 250)",
      "secondary-foreground": "oklch(0.28 0.04 255)",
      muted: "oklch(0.96 0.012 250)",
      "muted-foreground": "oklch(0.5 0.035 255)",
      accent: "oklch(0.93 0.035 250)",
      "accent-foreground": "oklch(0.3 0.08 255)",
      destructive: "oklch(0.58 0.22 27)",
      border: "oklch(0.9 0.018 250)",
      input: "oklch(0.9 0.018 250)",
      ring: "oklch(0.62 0.16 255)",
    });
  });

  it("keeps primary button interaction states opaque and WCAG AA compliant", () => {
    const tokens = themeTokens();
    const classes = buttonVariants();

    expect(classes).toContain("hover:bg-primary-hover");
    expect(classes).toContain("active:bg-primary-active");
    expect(classes).not.toContain("hover:bg-primary/90");
    expect(contrastRatio(tokens["primary-hover"], tokens["primary-foreground"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(tokens["primary-active"], tokens["primary-foreground"])).toBeGreaterThanOrEqual(4.5);
  });

  it("renders the login page for an unauthenticated browser session", async () => {
    server.use(http.get("/api/auth/me", () => HttpResponse.json({ detail: "Authentication required" }, { status: 401 })));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
  });

  it("shows a Chinese message when authentication status cannot be loaded", async () => {
    server.use(http.get("/api/auth/me", () => HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 })));
    renderApplication("/");
    expect(await screen.findByRole("alert")).toHaveTextContent("登录状态加载失败，请重试");
  });
});
