import { expect, test, type Page } from "@playwright/test";

type SettlementRecord = {
  id: number;
  company_id: number;
  company_name: string;
  opening_month: string;
  amount: number;
  status: "pending" | "confirmed";
  revision: number;
  created_at: string;
};

const stores = [
  { id: 1, name: "Berlin", timezone: "Europe/Berlin", company_settlement_enabled: true },
  { id: 2, name: "Roma", timezone: "Europe/Rome", company_settlement_enabled: true },
];

async function mockSettlementAnalysis(page: Page) {
  const companies = new Map<number, { id: number; name: string; is_active: boolean }[]>([
    [1, []],
    [2, []],
  ]);
  const records = new Map<number, SettlementRecord[]>([
    [1, []],
    [2, []],
  ]);

  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (value: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(value),
    });

    if (path === "/api/auth/me") {
      return json({ id: 1, username: "administrator", role: "admin", is_owner: true });
    }
    if (path === "/api/stores/accessible") return json(stores);
    if (/^\/api\/settlements\/\d+$/.test(path)) {
      const storeId = Number(path.split("/").at(-1));
      return json({
        store_id: storeId,
        store_name: stores.find((store) => store.id === storeId)?.name,
        company_settlement_enabled: true,
      });
    }

    const companiesMatch = path.match(/^\/api\/settlements\/(\d+)\/companies$/);
    if (companiesMatch) {
      const storeId = Number(companiesMatch[1]);
      if (request.method() === "GET") {
        return json(url.searchParams.has("archived") ? [] : companies.get(storeId));
      }
      const body = request.postDataJSON() as { name: string };
      const company = { id: storeId * 100 + 1, name: body.name.trim(), is_active: true };
      companies.get(storeId)!.push(company);
      return json(company, 201);
    }

    const monthMatch = path.match(/^\/api\/settlements\/(\d+)\/months\/(\d{4}-\d{2})$/);
    if (monthMatch) {
      const storeId = Number(monthMatch[1]);
      const month = monthMatch[2];
      const monthRecords = records.get(storeId)!.filter((record) => record.opening_month === month);
      const confirmed = monthRecords
        .filter((record) => record.status === "confirmed")
        .reduce((total, record) => total + record.amount, 0);
      const pending = monthRecords
        .filter((record) => record.status === "pending")
        .reduce((total, record) => total + record.amount, 0);
      return json({
        opening_month: month,
        records: monthRecords,
        daily_ledger_revenue: 900,
        confirmed_settlement_income: confirmed,
        pending_amount: pending,
        monthly_total: 900 + confirmed,
      });
    }

    const createRecordMatch = path.match(/^\/api\/settlements\/(\d+)\/records$/);
    if (createRecordMatch && request.method() === "POST") {
      const storeId = Number(createRecordMatch[1]);
      const body = request.postDataJSON() as { company_id: number; opening_month: string; amount: number };
      const company = companies.get(storeId)!.find((item) => item.id === body.company_id)!;
      const record: SettlementRecord = {
        id: 20,
        company_id: company.id,
        company_name: company.name,
        opening_month: body.opening_month,
        amount: body.amount,
        status: "pending",
        revision: 1,
        created_at: "2026-06-10T08:00:00",
      };
      records.get(storeId)!.push(record);
      return json(record, 201);
    }

    const recordMatch = path.match(/^\/api\/settlements\/(\d+)\/records\/(\d+)(?:\/(confirm|revoke-confirmation))?$/);
    if (recordMatch) {
      const storeId = Number(recordMatch[1]);
      const record = records.get(storeId)!.find((item) => item.id === Number(recordMatch[2]))!;
      if (request.method() === "PATCH") {
        const body = request.postDataJSON() as { company_id: number; amount: number; revision: number };
        record.company_id = body.company_id;
        record.company_name = companies.get(storeId)!.find((item) => item.id === body.company_id)!.name;
        record.amount = body.amount;
        record.revision += 1;
        return json(record);
      }
      if (recordMatch[3] === "confirm") record.status = "confirmed";
      if (recordMatch[3] === "revoke-confirmation") record.status = "pending";
      record.revision += 1;
      return json(record);
    }

    if (/^\/api\/database\/\d+\/records$/.test(path)) {
      return json({ items: [], categories: [], sum_daily_revenue: 0, total: 0, page: 1, page_size: 200 });
    }
    if (path === "/api/charts/1") {
      const isCompleteJune = url.searchParams.get("start") === "2026-06-01"
        && url.searchParams.get("end") === "2026-06-30";
      const confirmed = isCompleteJune
        ? records.get(1)!.filter((record) => record.opening_month === "2026-06" && record.status === "confirmed")
          .reduce((total, record) => total + record.amount, 0)
        : 0;
      return json({
        kpis: {
          total_revenue: 900 + confirmed,
          record_days: 1,
          open_days: 1,
          average_revenue: 900,
          primary_categories: [],
          total_wash_count: null,
          average_ticket: null,
        },
        range: {
          start: url.searchParams.get("start"),
          end: url.searchParams.get("end"),
          bucket: url.searchParams.get("bucket") ?? "day",
        },
        comparison_kpis: null,
        income_summary: {
          daily_ledger_revenue: 900,
          confirmed_settlement_income: confirmed,
          total_income: 900 + confirmed,
          includes_settlement_income: isCompleteJune,
        },
        classified_included_total: confirmed,
        daily: [{ date: "2026-06-10", revenue: 900 }],
        categories: confirmed > 0
          ? [{ category_id: null, category_name: "公司结算", amount: confirmed }]
          : [],
        excluded_categories: [],
        monthly: [{
          month: "2026-06",
          revenue: 900,
          daily_ledger_revenue: 900,
          confirmed_settlement_income: isCompleteJune ? confirmed : null,
          monthly_total_income: isCompleteJune ? 900 + confirmed : null,
        }],
        weather: [],
        weekday: [],
      });
    }
    if (path === "/api/charts/2") {
      return json({ detail: "not needed" }, 500);
    }
    return json({ detail: `unmocked ${request.method()} ${path}` }, 500);
  });
}

test("settlement corrections feed complete-month analysis without narrow-screen overflow", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-21T10:00:00Z") });
  await page.setViewportSize({ width: 320, height: 700 });
  await mockSettlementAnalysis(page);
  await page.goto("/settlements");

  await page.getByPlaceholder("输入结算公司名称").fill("Alpha");
  await page.getByRole("button", { name: "新增结算公司" }).click();
  await expect(page.getByLabel("结算公司", { exact: true }).locator("option").last()).toHaveText("Alpha");

  await page.getByLabel("开票月份").fill("2026-06");
  await page.getByLabel("结算公司", { exact: true }).selectOption({ label: "Alpha" });
  await page.getByLabel("金额（整数欧元）").fill("120");
  await page.getByRole("button", { name: "登记待到账记录" }).click();
  await expect(page.getByRole("button", { name: "编辑Alpha开票记录" })).toBeVisible();

  await page.getByRole("button", { name: "编辑Alpha开票记录" }).click();
  await page.getByLabel("编辑金额（整数欧元）").fill("250");
  await page.getByRole("button", { name: "保存开票记录修改" }).click();
  await expect(page.getByText("开票记录已修改", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "确认Alpha开票记录到账" }).click();
  await page.getByRole("button", { name: "确认到账", exact: true }).click();
  await expect(page.getByText("€1,150")).toBeVisible();
  await page.getByRole("button", { name: "撤销Alpha开票记录到账确认" }).click();
  await page.getByRole("button", { name: "确认撤销到账确认" }).click();
  await expect(page.getByText("€900").last()).toBeVisible();
  await page.getByRole("button", { name: "确认Alpha开票记录到账" }).click();
  await page.getByRole("button", { name: "确认到账", exact: true }).click();

  await page.getByLabel("开票月份").fill("2026-07");
  await expect(page.getByText("本月暂无开票记录。")).toBeVisible();
  const mobileStore = page.getByTestId("mobile-store-picker").getByLabel("门店");
  await mobileStore.selectOption("2");
  await expect(mobileStore).toHaveValue("2");
  await mobileStore.selectOption("1");
  await expect(page.getByLabel("开票月份")).toHaveValue("2026-07");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.goto("/database");
  await page.getByLabel("经营分析日期范围").getByRole("button", { name: "上月" }).click();
  const summary = page.getByRole("region", { name: "月度收入汇总" });
  await expect(summary.getByText("日常营业额")).toBeVisible();
  await expect(summary.getByText("公司结算收入")).toBeVisible();
  await expect(summary.getByText("月度总收入")).toBeVisible();
  await expect(summary.getByText("€900")).toBeVisible();
  await expect(summary.getByText("€250")).toBeVisible();
  await expect(summary.getByText(/€1[.,]150/)).toBeVisible();
  const incomeCategories = page.getByLabel("收入分类");
  await expect(incomeCategories.getByText("公司结算")).toBeVisible();
  await expect(incomeCategories.getByText("€250")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
