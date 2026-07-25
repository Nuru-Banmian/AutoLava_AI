import { expect, test, type Locator, type Page } from "@playwright/test";

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
  let nextCompanyId = 30;
  const activeCompanies = [
    { id: 10, name: "Alpha Fleet Services", is_active: true },
    { id: 11, name: "Beta Logistics", is_active: true },
    ...Array.from({ length: 10 }, (_, index) => ({
      id: 12 + index,
      name: `Fleet ${String(index + 1).padStart(2, "0")}`,
      is_active: true,
    })),
  ];
  const archivedCompanies = [
    { id: 25, name: "Historic Transport", is_active: false },
  ];
  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    const json = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

    if (path === "/api/auth/me") return json({ id: 1, username: "administrator", role: "admin", is_owner: true });
    if (path === "/api/stores/accessible") return json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin", company_settlement_enabled: true }]);
    if (path === "/api/settlements/1") return json({ store_id: 1, store_name: "Berlin", company_settlement_enabled: true });
    if (path === "/api/settlements/1/companies" && method === "GET") {
      return json(url.searchParams.has("archived") ? archivedCompanies : activeCompanies);
    }
    if (path === "/api/settlements/1/companies" && method === "POST") {
      const body = route.request().postDataJSON() as { name: string };
      const company = { id: nextCompanyId++, name: body.name.trim(), is_active: true };
      activeCompanies.push(company);
      return json(company, 201);
    }
    const companyMatch = path.match(/^\/api\/settlements\/1\/companies\/(\d+)(?:\/(archive|restore))?$/);
    if (companyMatch) {
      const id = Number(companyMatch[1]);
      const action = companyMatch[2];
      const source = action === "restore" ? archivedCompanies : activeCompanies;
      const company = [...activeCompanies, ...archivedCompanies].find((candidate) => candidate.id === id);
      if (!company) return json({ detail: "not found" }, 404);
      if (method === "PATCH") {
        const body = route.request().postDataJSON() as { name: string };
        company.name = body.name.trim();
        return json(company);
      }
      if (method === "POST" && action) {
        source.splice(source.findIndex((candidate) => candidate.id === id), 1);
        company.is_active = action === "restore";
        (company.is_active ? activeCompanies : archivedCompanies).push(company);
        return json(company);
      }
      if (method === "DELETE") {
        if (id === 25) return json({ detail: "该结算公司已有开票历史，只能归档" }, 409);
        const owningList = company.is_active ? activeCompanies : archivedCompanies;
        owningList.splice(owningList.findIndex((candidate) => candidate.id === id), 1);
        return route.fulfill({ status: 204 });
      }
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

async function openSettlementWorkbench(page: Page, width: number, height: number) {
  await page.clock.install({ time: new Date("2026-07-21T10:00:00Z") });
  await page.setViewportSize({ width, height });
  const requestedMonths = await mockSettlementWorkbench(page);
  await page.goto("/settlements");
  return requestedMonths;
}

async function expectWorkbenchOrder(page: Page) {
  const workbenchSections = [
    page.getByRole("heading", { name: "公司结算" }).locator("../.."),
    page.getByRole("region", { name: "月度汇总" }),
    page.getByRole("form", { name: "登记开票记录" }).locator(".."),
    page.getByRole("region", { name: "开票记录列表" }),
    page.getByRole("region", { name: "结算公司管理" }),
  ];
  const boxes = await Promise.all(workbenchSections.map((section) => section.boundingBox()));
  expect(boxes.every((box) => box !== null)).toBe(true);
  expect(boxes.slice(0, -1).every((box, index) => (
    box!.y + box!.height <= boxes[index + 1]!.y + 1
  ))).toBe(true);
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => ({
    documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    bodyFits: document.body.scrollWidth <= document.body.clientWidth,
  }))).toEqual({ documentFits: true, bodyFits: true });
}

async function expectRecordRowsUseAtMostTwoLines(rows: Locator) {
  for (const row of await rows.all()) {
    const cellBoxes = await row.locator(":scope > *").evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().toJSON()));
    expect(new Set(cellBoxes.map((box) => Math.round(box.y + box.height / 2))).size).toBeLessThanOrEqual(2);
  }
}

test("1280x900 monthly workbench keeps summaries and record columns aligned", async ({ page }) => {
  const requestedMonths = await openSettlementWorkbench(page, 1280, 900);

  const summary = page.getByRole("region", { name: "月度汇总" });
  const registration = page.getByRole("form", { name: "登记开票记录" });
  const recordsRegion = page.getByRole("region", { name: "开票记录列表" });
  await expect(summary.getByText("月度总收入")).toBeVisible();
  const summaryCards = summary.locator("dd");
  await expect(summaryCards).toHaveCount(4);
  const summaryBoxes = await summaryCards.evaluateAll((nodes) => nodes.map((node) => node.parentElement!.getBoundingClientRect().toJSON()));
  expect(new Set(summaryBoxes.map((box) => Math.round(box.y))).size).toBe(1);
  const registrationControls = [
    registration.getByLabel("结算公司"),
    registration.getByLabel("金额（整数欧元）"),
    registration.getByRole("button", { name: "登记待到账记录" }),
  ];
  const registrationBoxes = await Promise.all(registrationControls.map((control) => control.boundingBox()));
  expect(registrationBoxes.every((box) => box !== null)).toBe(true);
  expect(new Set(registrationBoxes.map((box) => Math.round(box!.y))).size).toBe(1);

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
  await expect(page.getByRole("button", { name: "确认Alpha Fleet Services开票记录到账" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Alpha Fleet Services开票记录更多操作" })).toBeVisible();
  await expect(page.getByRole("button", { name: "结算公司管理" })).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("tab", { name: "使用中（12）" })).toBeHidden();

  const nextMonth = page.getByRole("button", { name: "后一月" });
  await expect(nextMonth).toBeDisabled();
  await page.getByRole("button", { name: "前一月" }).click();
  await expect(page.getByRole("textbox", { name: "开票月份" })).toHaveValue("2026-06");
  await expect.poll(() => requestedMonths).toContain("2026-06");
  await expectWorkbenchOrder(page);
  await expectNoHorizontalOverflow(page);
});

test("390x844 record and company actions stay compact and keyboard-operable", async ({ page }) => {
  await openSettlementWorkbench(page, 390, 844);

  const recordsRegion = page.getByRole("region", { name: "开票记录列表" });
  await expect(recordsRegion.getByText("公司名称")).toBeHidden();
  const rows = recordsRegion.getByRole("listitem");
  await expect(rows).toHaveCount(2);
  await expectRecordRowsUseAtMostTwoLines(rows);

  await expect(page.getByRole("button", { name: "确认Alpha Fleet Services开票记录到账" })).toBeVisible();
  await expect(page.getByRole("button", { name: "编辑Alpha Fleet Services开票记录" })).toHaveCount(0);
  const pendingMenu = page.getByRole("button", { name: "Alpha Fleet Services开票记录更多操作" });
  await pendingMenu.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menuitem", { name: "编辑Alpha Fleet Services开票记录" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "删除Alpha Fleet Services开票记录" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(pendingMenu).toBeFocused();
  await expect(page.getByRole("menu")).toHaveCount(0);

  const confirmedMenu = page.getByRole("button", { name: "Beta Logistics开票记录更多操作" });
  await confirmedMenu.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menuitem", { name: "撤销Beta Logistics开票记录到账确认" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(confirmedMenu).toBeFocused();
  const pendingColor = await recordsRegion.getByText("待到账", { exact: true }).evaluate((node) => getComputedStyle(node).backgroundColor);
  const confirmedColor = await recordsRegion.getByText("已确认", { exact: true }).evaluate((node) => getComputedStyle(node).backgroundColor);
  expect(pendingColor).not.toBe("rgba(0, 0, 0, 0)");
  expect(confirmedColor).not.toBe(pendingColor);

  const companyManagement = page.getByRole("button", { name: "结算公司管理" });
  await companyManagement.focus();
  await page.keyboard.press("Enter");
  await expect(companyManagement).toHaveAttribute("aria-expanded", "true");
  const activeTab = page.getByRole("tab", { name: /^使用中/ });
  const archivedTab = page.getByRole("tab", { name: /^已归档/ });
  await expect(activeTab).toHaveAttribute("aria-selected", "true");
  await expect(archivedTab).toHaveAttribute("aria-selected", "false");
  await expect(page.getByRole("button", { name: "新增结算公司" })).toBeVisible();

  const activeList = page.getByRole("region", { name: "使用中结算公司（12）" });
  await expect(activeList.getByRole("listitem")).toHaveCount(12);
  await expect.poll(() => activeList.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);

  const alphaMenuButton = page.getByRole("button", { name: "Alpha Fleet Services更多操作" });
  await alphaMenuButton.focus();
  await page.keyboard.press("ArrowDown");
  const alphaMenu = page.getByRole("menu", { name: "Alpha Fleet Services操作" });
  await expect(alphaMenu).toBeVisible();
  await expect(alphaMenu.getByRole("menuitem", { name: "重命名Alpha Fleet Services" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(alphaMenu.getByRole("menuitem", { name: "归档Alpha Fleet Services" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(alphaMenuButton).toBeFocused();

  await activeList.evaluate((node) => { node.scrollTop = node.scrollHeight; });
  const lastCompanyMenuButton = page.getByRole("button", { name: "Fleet 10更多操作" });
  await lastCompanyMenuButton.click();
  const lastCompanyMenu = page.getByRole("menu", { name: "Fleet 10操作" });
  await expect(lastCompanyMenu).toBeVisible();
  const activeListBox = await activeList.boundingBox();
  const lastCompanyMenuBox = await lastCompanyMenu.boundingBox();
  expect(activeListBox).not.toBeNull();
  expect(lastCompanyMenuBox).not.toBeNull();
  expect(lastCompanyMenuBox!.y + lastCompanyMenuBox!.height).toBeLessThanOrEqual(activeListBox!.y + activeListBox!.height);
  await page.keyboard.press("Escape");
  await activeList.evaluate((node) => { node.scrollTop = 0; });

  await alphaMenuButton.click();
  await alphaMenu.getByRole("menuitem", { name: "重命名Alpha Fleet Services" }).click();
  const renameInput = page.getByRole("textbox", { name: "重命名Alpha Fleet Services" });
  await renameInput.fill("Alpha Fleet");
  await page.getByRole("button", { name: "保存名称" }).click();
  await expect(page.getByTitle("Alpha Fleet")).toBeVisible();

  const renamedCompanyMenuButton = page.getByRole("button", { name: "Alpha Fleet更多操作" });
  await renamedCompanyMenuButton.focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("tab", { name: "使用中（11）" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "已归档（2）" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Beta Logistics更多操作" })).toBeFocused();

  await activeTab.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "已归档（2）" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("region", { name: "已归档结算公司（2）" })).toBeVisible();
  await expect(page.getByRole("button", { name: "新增结算公司" })).toBeHidden();

  await page.getByRole("button", { name: "Alpha Fleet更多操作" }).click();
  await page.getByRole("menuitem", { name: "恢复Alpha Fleet" }).click();
  await expect(page.getByRole("tab", { name: "使用中（12）" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "已归档（1）" })).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Historic Transport更多操作" }).click();
  await page.getByRole("menuitem", { name: "永久删除Historic Transport" }).click();
  await expect(page.getByRole("alert")).toContainText("已有开票历史，只能归档");

  await page.getByRole("tab", { name: "使用中（12）" }).click();
  await page.getByRole("textbox", { name: "新结算公司名称" }).fill("Disposable Fleet");
  await page.getByRole("button", { name: "新增结算公司" }).click();
  await expect(page.getByRole("tab", { name: "使用中（13）" })).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Disposable Fleet更多操作" }).click();
  await page.getByRole("menuitem", { name: "永久删除Disposable Fleet" }).click();
  await expect(page.getByRole("tab", { name: "使用中（12）" })).toBeVisible();
  await expectWorkbenchOrder(page);
  await expectNoHorizontalOverflow(page);
});

test("320px workbench wraps summaries and controls without horizontal overflow", async ({ page }) => {
  await openSettlementWorkbench(page, 320, 844);

  const summaryValues = page.getByRole("region", { name: "月度汇总" }).locator("dd");
  await expect(summaryValues).toHaveCount(4);
  const summaryBoxes = await summaryValues.evaluateAll((nodes) => nodes.map((node) => node.parentElement!.getBoundingClientRect().toJSON()));
  expect(new Set(summaryBoxes.map((box) => Math.round(box.y))).size).toBe(4);

  const monthNavigationBox = await page.getByRole("group", { name: "月份导航" }).boundingBox();
  expect(monthNavigationBox).not.toBeNull();
  expect(monthNavigationBox!.x).toBeGreaterThanOrEqual(0);
  expect(monthNavigationBox!.x + monthNavigationBox!.width).toBeLessThanOrEqual(320);
  await expect(page.getByRole("button", { name: "确认Alpha Fleet Services开票记录到账" })).toBeVisible();
  const rows = page.getByRole("region", { name: "开票记录列表" }).getByRole("listitem");
  await expectRecordRowsUseAtMostTwoLines(rows);
  await expect(page.getByRole("button", { name: "Beta Logistics开票记录更多操作" })).toBeVisible();
  await expectWorkbenchOrder(page);
  await expectNoHorizontalOverflow(page);
});
