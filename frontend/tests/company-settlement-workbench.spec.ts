import { expect, test, type Page } from "@playwright/test";

const records = [
  {
    id: 20,
    company_id: 10,
    company_name: "Alpha Fleet Services",
    opening_month: "2026-07",
    amount: 120,
    status: "pending",
    revision: 1,
    created_at: "2026-07-10T08:00:00",
  },
  {
    id: 21,
    company_id: 11,
    company_name: "Beta Logistics",
    opening_month: "2026-07",
    amount: 3450,
    status: "confirmed",
    revision: 2,
    created_at: "2026-07-11T08:00:00",
  },
] as const;

async function mockSettlementWorkbench(page: Page) {
  const requestedMonths: string[] = [];
  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

    if (path === "/api/auth/me") return json({ id: 1, username: "administrator", role: "admin", is_owner: true });
    if (path === "/api/stores/accessible") return json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin", company_settlement_enabled: true }]);
    if (path === "/api/settlements/1") return json({ store_id: 1, store_name: "Berlin", company_settlement_enabled: true });
    if (path === "/api/settlements/1/companies") {
      return json(url.searchParams.has("archived") ? [] : [
        { id: 10, name: "Alpha Fleet Services", is_active: true },
        { id: 11, name: "Beta Logistics", is_active: true },
      ]);
    }
    const monthMatch = path.match(/^\/api\/settlements\/1\/months\/(\d{4}-\d{2})$/);
    if (monthMatch) {
      const month = monthMatch[1];
      requestedMonths.push(month);
      const monthRecords = month === "2026-07" ? records : [];
      return json({
        opening_month: month,
        records: monthRecords,
        daily_ledger_revenue: month === "2026-07" ? 900 : 600,
        confirmed_settlement_income: month === "2026-07" ? 3450 : 0,
        pending_amount: month === "2026-07" ? 120 : 0,
        monthly_total: month === "2026-07" ? 4350 : 600,
      });
    }
    return json({ detail: `unmocked ${route.request().method()} ${path}` }, 500);
  });
  return requestedMonths;
}

test("1280x900 monthly workbench keeps summaries and record columns aligned", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-21T10:00:00Z") });
  await page.setViewportSize({ width: 1280, height: 900 });
  const requestedMonths = await mockSettlementWorkbench(page);
  await page.goto("/settlements");

  const summary = page.getByRole("region", { name: "月度汇总" });
  const recordsRegion = page.getByRole("region", { name: "开票记录列表" });
  await expect(summary.getByText("月度总收入")).toBeVisible();
  const summaryCards = summary.locator("dd");
  await expect(summaryCards).toHaveCount(4);
  const summaryBoxes = await summaryCards.evaluateAll((nodes) => nodes.map((node) => node.parentElement!.getBoundingClientRect().toJSON()));
  expect(new Set(summaryBoxes.map((box) => Math.round(box.y))).size).toBe(1);

  const columnHeader = recordsRegion.getByText("公司名称").locator("..");
  await expect(columnHeader).toBeVisible();
  const rows = recordsRegion.getByRole("listitem");
  await expect(rows).toHaveCount(2);
  for (const columnIndex of [0, 1, 2, 3]) {
    const headerBox = await columnHeader.locator(":scope > *").nth(columnIndex).boundingBox();
    const rowBoxes = await rows.locator(`:scope > :nth-child(${columnIndex + 1})`).evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().toJSON()));
    expect(headerBox).not.toBeNull();
    expect(rowBoxes.every((box) => Math.abs(box.x - headerBox!.x) <= 1)).toBe(true);
  }
  await expect.poll(() => rows.nth(0).locator(":scope > :nth-child(2)").evaluate((node) => getComputedStyle(node).textAlign)).toBe("right");
  await expect(recordsRegion.getByText("待到账", { exact: true })).toBeVisible();
  await expect(recordsRegion.getByText("已确认", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "活动结算公司" })).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("button", { name: "归档结算公司" })).toHaveAttribute("aria-expanded", "false");

  const nextMonth = page.getByRole("button", { name: "后一月" });
  await expect(nextMonth).toBeDisabled();
  await page.getByRole("button", { name: "前一月" }).click();
  await expect(page.getByRole("textbox", { name: "开票月份" })).toHaveValue("2026-06");
  await expect.poll(() => requestedMonths).toContain("2026-06");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("390x844 record cards preserve states, actions, and keyboard company management", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-21T10:00:00Z") });
  await page.setViewportSize({ width: 390, height: 844 });
  await mockSettlementWorkbench(page);
  await page.goto("/settlements");

  const recordsRegion = page.getByRole("region", { name: "开票记录列表" });
  await expect(recordsRegion.getByText("公司名称")).toBeHidden();
  const rows = recordsRegion.getByRole("listitem");
  await expect(rows).toHaveCount(2);
  const firstRowCellBoxes = await rows.nth(0).locator(":scope > *").evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().toJSON()));
  expect(new Set(firstRowCellBoxes.map((box) => Math.round(box.y))).size).toBeGreaterThanOrEqual(3);

  await expect(page.getByRole("button", { name: "确认Alpha Fleet Services开票记录到账" })).toBeVisible();
  await expect(page.getByRole("button", { name: "编辑Alpha Fleet Services开票记录" })).toBeVisible();
  await expect(page.getByRole("button", { name: "删除Alpha Fleet Services开票记录" })).toBeVisible();
  await expect(page.getByRole("button", { name: "撤销Beta Logistics开票记录到账确认" })).toBeVisible();
  const pendingColor = await recordsRegion.getByText("待到账", { exact: true }).evaluate((node) => getComputedStyle(node).backgroundColor);
  const confirmedColor = await recordsRegion.getByText("已确认", { exact: true }).evaluate((node) => getComputedStyle(node).backgroundColor);
  expect(pendingColor).not.toBe("rgba(0, 0, 0, 0)");
  expect(confirmedColor).not.toBe(pendingColor);

  const activeCompanies = page.getByRole("button", { name: "活动结算公司" });
  await activeCompanies.focus();
  await page.keyboard.press("Enter");
  await expect(activeCompanies).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("button", { name: "新增结算公司" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("320px workbench wraps summaries and controls without horizontal overflow", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-21T10:00:00Z") });
  await page.setViewportSize({ width: 320, height: 844 });
  await mockSettlementWorkbench(page);
  await page.goto("/settlements");

  const summaryValues = page.getByRole("region", { name: "月度汇总" }).locator("dd");
  await expect(summaryValues).toHaveCount(4);
  const summaryBoxes = await summaryValues.evaluateAll((nodes) => nodes.map((node) => node.parentElement!.getBoundingClientRect().toJSON()));
  expect(new Set(summaryBoxes.map((box) => Math.round(box.y))).size).toBe(4);

  const monthNavigationBox = await page.getByRole("group", { name: "月份导航" }).boundingBox();
  expect(monthNavigationBox).not.toBeNull();
  expect(monthNavigationBox!.x).toBeGreaterThanOrEqual(0);
  expect(monthNavigationBox!.x + monthNavigationBox!.width).toBeLessThanOrEqual(320);
  await expect(page.getByRole("button", { name: "确认Alpha Fleet Services开票记录到账" })).toBeVisible();
  await expect(page.getByRole("button", { name: "撤销Beta Logistics开票记录到账确认" })).toBeVisible();
  expect(await page.evaluate(() => ({
    documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    bodyFits: document.body.scrollWidth <= document.body.clientWidth,
  }))).toEqual({ documentFits: true, bodyFits: true });
});
