import { expect, test, type Locator, type Page } from "@playwright/test";
import type { CategoryDescriptor, LedgerBody, RecordSnapshot } from "../src/api/types";
import { weatherOptions } from "../src/test/weather-options";

const today = "2026-07-17";
const yesterday = "2026-07-16";
const configRevision = 7;
const categories: CategoryDescriptor[] = Array.from({ length: 13 }, (_, index) => ({
  id: index + 1,
  name: `收入项目${String(index + 1).padStart(2, "0")}用于检验超长名称换行及字段对应`,
  include_in_total: index < 9,
  is_active: true,
  sort_order: index,
}));

async function mockHomeLedger(page: Page, direct = false) {
  const records = new Map<string, RecordSnapshot>();
  const accepted: { storeId: number; date: string; body: LedgerBody }[] = [];
  const attempts: { storeId: number; date: string; body: LedgerBody }[] = [];
  const reads: string[] = [];
  const contractErrors: string[] = [];
  let saveFailures = 0;
  let nextId = 1;

  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/me") return json({ id: 1, username: "fixture-operator", role: "user", is_owner: false });
    if (path === "/api/stores/accessible") return json([
      { id: 1, name: "用于检验换行的特别长名称测试门店一", timezone: "Europe/Rome", is_active: true, company_settlement_enabled: false, wash_count_enabled: true },
      { id: 2, name: "测试门店二", timezone: "Europe/Rome", is_active: true, company_settlement_enabled: false, wash_count_enabled: true },
    ]);
    if (/^\/api\/dashboard\/\d+$/.test(path)) return json([
      // An old briefing is deliberately inconsistent with the exact-date ledger.
      { card_type: "today", state: "recorded", revenue: 88888, generated_at: `${yesterday}T04:00:00Z` },
      { card_type: "yesterday", state: "missing", revenue: null },
      { card_type: "tomorrow", state: "forecast", weather: "多云", weekday: "星期六", temperature_min: "16", temperature_max: "25", precipitation: "0", hint: null },
    ]);
    if (/^\/api\/dashboard\/\d+\/refresh$/.test(path)) return json([]);
    if (path === "/api/ledger/weather-options") return json(weatherOptions);
    if (/^\/api\/weather\/\d+\/\d{4}-\d{2}-\d{2}$/.test(path)) return json({ weather: null, weather_code: null, temperature_max: null, temperature_min: null, precipitation: null });
    const configMatch = path.match(/^\/api\/income-config\/(\d+)\/current$/);
    if (configMatch) {
      const storeId = Number(configMatch[1]);
      const composed = storeId === 1 && !direct;
      return json({ store_id: storeId, revision: configRevision, enabled: composed, formula: composed ? categories.filter((item) => item.include_in_total).map((item) => item.name).join(" + ") : "", items: composed ? categories.map((item) => ({ ...item, store_id: storeId, archived_at: null })) : [] });
    }
    const ledgerMatch = path.match(/^\/api\/ledger\/(\d+)\/(\d{4}-\d{2}-\d{2})$/);
    if (ledgerMatch) {
      const storeId = Number(ledgerMatch[1]);
      const date = ledgerMatch[2];
      const key = `${storeId}:${date}`;
      const existing = records.get(key);
      if (request.method() === "GET") {
        reads.push(key);
        return existing ? json(existing) : json({ detail: "Record not found" }, 404);
      }
      if (request.method() === "PUT") {
        const body = request.postDataJSON() as LedgerBody;
        attempts.push({ storeId, date, body });
        const composed = existing ? existing.income_mode === "composed" : storeId === 1 && !direct;
        const validRevision = body.expected_config_revision === configRevision
          && body.expected_identity === (existing?.identity ?? null)
          && body.expected_revision === (existing?.revision ?? null);
        const validAmounts = body.items.every((item) => Number.isSafeInteger(item.amount) && item.amount >= 0)
          && (composed ? body.daily_revenue === null && body.items.length === categories.length : body.items.length === 0 && Number.isSafeInteger(body.daily_revenue) && Number(body.daily_revenue) >= 0);
        if (!validRevision || !validAmounts || date > today) {
          contractErrors.push(`${key}: expected revisions, integer amounts or date did not match`);
          return json({ detail: "模拟接口拒绝不符合保存协议的请求" }, 422);
        }
        if (saveFailures > 0) {
          saveFailures -= 1;
          return json({ detail: "模拟保存失败，请重试" }, 503);
        }
        const id = existing?.id ?? nextId++;
        const now = `${date}T12:00:00Z`;
        const isRest = body.is_open === "休息";
        const items = composed ? body.items.map((item, index) => {
          const category = categories.find((candidate) => candidate.id === item.category_id)!;
          return { id: id * 100 + index, category_id: category.id, category_name: category.name, include_in_total: category.include_in_total, sort_order: category.sort_order, amount: isRest ? 0 : item.amount, created_at: now, updated_at: now };
        }) : [];
        const revenue = isRest ? 0 : composed ? items.filter((item) => item.include_in_total).reduce((sum, item) => sum + item.amount, 0) : body.daily_revenue!;
        const saved: RecordSnapshot = {
          id, store_id: storeId, date, identity: existing?.identity ?? `fixture-${storeId}-${id}`, revision: (existing?.revision ?? 0) + 1, config_revision: configRevision,
          daily_revenue: revenue, income_mode: composed ? "composed" : "legacy_total", is_open: body.is_open, items,
          wash_count: isRest ? 0 : body.wash_count ?? null, activity: body.activity ?? null,
          weather: body.weather ?? existing?.weather ?? null, weather_auto: null, weather_code: null, weather_legacy: false, weather_edited: body.weather_edited,
          temperature_max: null, temperature_min: null, precipitation: null, scanned: false, created_by: 1, updated_by: 1, created_at: existing?.created_at ?? now, updated_at: now,
        };
        records.set(key, saved);
        accepted.push({ storeId, date, body });
        return json({ id, identity: saved.identity, revision: saved.revision, config_revision: configRevision, date, daily_revenue: revenue }, existing ? 200 : 201);
      }
    }
    const databaseMatch = path.match(/^\/api\/database\/(\d+)\/records$/);
    if (databaseMatch) {
      const storeId = Number(databaseMatch[1]);
      const start = url.searchParams.get("start") ?? "";
      const end = url.searchParams.get("end") ?? "";
      const pageNumber = Number(url.searchParams.get("page"));
      const pageSize = Number(url.searchParams.get("page_size"));
      const matching = [...records.values()].filter((item) => item.store_id === storeId && item.date >= start && item.date <= end);
      return json({ items: matching.slice((pageNumber - 1) * pageSize, pageNumber * pageSize), categories: storeId === 1 && !direct ? categories : [], sum_daily_revenue: matching.reduce((sum, item) => sum + item.daily_revenue, 0), total: matching.length, page: pageNumber, page_size: pageSize });
    }
    contractErrors.push(`unhandled ${request.method()} ${path}`);
    return json({ detail: "Unexpected fixture request" }, 500);
  });
  return { records, accepted, attempts, reads, contractErrors, failNextSave() { saveFailures += 1; } };
}

function homeState(page: Page) { return page.getByRole("region", { name: "今日状态" }); }
function navigation(page: Page, width: number) { return page.getByRole("navigation", { name: width < 768 ? "移动导航" : "主导航" }); }

async function waitForSaved(page: Page) {
  await expect(page.getByRole("status").filter({ hasText: "保存成功" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^(保存今日记录|保存修改|补记历史记录)$/ })).toBeEnabled();
}

async function assertNoOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
}

async function assertReachable(locator: Locator) {
  await locator.evaluate((element) => element.scrollIntoView({ block: "center" }));
  await expect(locator).toBeInViewport();
  expect(await locator.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
    return hit === element || element.contains(hit);
  })).toBe(true);
}

async function assertIncomeLayout(page: Page, width: number) {
  const fields = page.getByRole("group", { name: "收入项目" }).locator("input");
  await expect(fields).toHaveCount(13);
  const boxes = await fields.evaluateAll((elements) => elements.map((element) => {
    const box = element.getBoundingClientRect();
    return { x: box.x, y: box.y, width: box.width, height: box.height, fontSize: parseFloat(getComputedStyle(element).fontSize) };
  }));
  expect(boxes.filter((box) => Math.abs(box.y - boxes[0].y) < 2)).toHaveLength(width < 768 ? 2 : width < 1280 ? 3 : 4);
  for (const box of boxes) {
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.fontSize).toBeGreaterThanOrEqual(16);
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
  }
  for (const category of categories) {
    const input = page.getByLabel(category.name, { exact: true });
    await expect(input).toHaveAttribute("inputmode", "numeric");
    await expect(input).not.toHaveAttribute("placeholder", /€|欧元/);
  }
  await expect(page.getByRole("group", { name: "收入项目" }).getByText(/^€$/)).toHaveCount(0);
  await expect(page.getByLabel("事件", { exact: true })).toBeVisible();
  await assertNoOverflow(page);
}

for (const width of [320, 390, 768, 1024, 1280]) {
  test(`${width}px: homepage creates and modifies categorized ledger, then rereads today's fact`, async ({ page }) => {
    await page.clock.install({ time: new Date(`${today}T12:00:00Z`) });
    await page.setViewportSize({ width, height: 844 });
    const flow = await mockHomeLedger(page);
    await page.goto("/");
    await expect(homeState(page)).toContainText(today);
    await expect(homeState(page)).toContainText("今日尚未记录");
    await expect(homeState(page)).not.toContainText("88.888");
    await expect(homeState(page).getByRole("link", { name: "立即记账" })).toHaveAttribute("href", `/ledger?date=${today}`);
    await homeState(page).getByRole("link", { name: "立即记账" }).click();
    await expect(page).toHaveURL(new RegExp(`ledger\\?date=${today}$`));
    await expect(page.getByLabel(categories[0].name, { exact: true })).toBeVisible();
    await assertIncomeLayout(page, width);
    await page.getByLabel(categories[0].name, { exact: true }).fill("120");
    await page.getByLabel(categories[1].name, { exact: true }).fill("30");
    await page.getByLabel(categories[12].name, { exact: true }).fill("999");
    await page.getByLabel("洗车数量", { exact: true }).fill("6");
    await page.getByLabel("事件", { exact: true }).fill("可控测试事件");
    await expect(page.getByText("合计金额 €150", { exact: true })).toBeVisible();
    if (width === 320) {
      // Reduced layout height checks occlusion and scroll access; it is not a physical keyboard test.
      await page.setViewportSize({ width, height: 360 });
      const lastIncome = page.getByLabel(categories[12].name, { exact: true });
      await assertReachable(lastIncome);
      await lastIncome.focus();
      await expect(lastIncome).toBeFocused();
      await assertReachable(page.getByRole("button", { name: "保存今日记录", exact: true }));
    }
    await page.getByRole("button", { name: "保存今日记录", exact: true }).click();
    await waitForSaved(page);
    expect(flow.accepted).toHaveLength(1);
    expect(flow.accepted[0].body).toMatchObject({ expected_identity: null, expected_revision: null, expected_config_revision: configRevision, daily_revenue: null });
    expect(flow.records.get(`1:${today}`)).toMatchObject({ daily_revenue: 150, wash_count: 6, activity: "可控测试事件", revision: 1 });
    if (width === 320) await page.setViewportSize({ width, height: 844 });
    const firstReadCount = flow.reads.length;
    await navigation(page, width).getByRole("link", { name: "首页", exact: true }).click();
    await expect(homeState(page)).toContainText("今日已记录");
    await expect(homeState(page)).toContainText("营业状态：营业");
    await expect(homeState(page)).toContainText("总营业额 €150");
    await expect.poll(() => flow.reads.length).toBeGreaterThan(firstReadCount);
    await homeState(page).getByRole("link", { name: "修改今日台账" }).click();
    await expect(page.getByLabel(categories[0].name, { exact: true })).toHaveValue("120");
    await expect(page.getByLabel(categories[12].name, { exact: true })).toHaveValue("999");
    await page.getByLabel(categories[0].name, { exact: true }).fill("220");
    const status = width === 320 || width === 1280 ? "休息" : "提前休息";
    await page.getByLabel("状态", { exact: true }).selectOption(status);
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await waitForSaved(page);
    expect(flow.accepted).toHaveLength(2);
    expect(flow.accepted[1].body).toMatchObject({ expected_identity: "fixture-1-1", expected_revision: 1, expected_config_revision: configRevision, is_open: status });
    const amount = status === "休息" ? 0 : 250;
    expect(flow.records.get(`1:${today}`)).toMatchObject({ daily_revenue: amount, wash_count: status === "休息" ? 0 : 6, revision: 2 });
    if (status === "休息") {
      expect(flow.accepted[1].body.items.every((item) => item.amount === 0)).toBe(true);
      await expect(page.getByLabel(categories[0].name, { exact: true })).toHaveValue("0");
    }
    const secondReadCount = flow.reads.length;
    await navigation(page, width).getByRole("link", { name: "首页", exact: true }).click();
    await expect(homeState(page)).toContainText(`营业状态：${status}`);
    await expect(homeState(page)).toContainText(`总营业额 €${amount}`);
    await expect.poll(() => flow.reads.length).toBeGreaterThan(secondReadCount);
    await assertNoOverflow(page);
    expect(flow.contractErrors).toEqual([]);
  });
}

test("direct total keeps a failed draft, retries, and saves historical dates without changing today's fact", async ({ page }) => {
  await page.clock.install({ time: new Date(`${today}T12:00:00Z`) });
  await page.setViewportSize({ width: 390, height: 844 });
  const flow = await mockHomeLedger(page, true);
  await page.goto("/");
  await homeState(page).getByRole("link", { name: "立即记账" }).click();
  await page.getByLabel("当日营业额", { exact: true }).fill("150");
  await page.getByLabel("洗车数量", { exact: true }).fill("3");
  flow.failNextSave();
  await page.getByRole("button", { name: "保存今日记录", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("模拟保存失败，请重试");
  await expect(page.getByLabel("当日营业额", { exact: true })).toHaveValue("150");
  expect(flow.accepted).toHaveLength(0);
  await page.getByRole("button", { name: "保存今日记录", exact: true }).click();
  await waitForSaved(page);
  expect(flow.attempts).toHaveLength(2);
  expect(flow.records.get(`1:${today}`)).toMatchObject({ daily_revenue: 150, income_mode: "legacy_total", items: [] });
  await navigation(page, 390).getByRole("link", { name: "首页", exact: true }).click();
  await expect(homeState(page)).toContainText("总营业额 €150");
  await homeState(page).getByRole("link", { name: "修改今日台账" }).click();
  await expect(page.getByLabel("当日营业额", { exact: true })).toHaveValue("150");
  await page.getByLabel("当日营业额", { exact: true }).fill("175");
  await page.getByLabel("状态", { exact: true }).selectOption("提前休息");
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  await waitForSaved(page);
  expect(flow.accepted[1].body).toMatchObject({ daily_revenue: 175, items: [], expected_identity: "fixture-1-1", expected_revision: 1 });
  await navigation(page, 390).getByRole("link", { name: "首页", exact: true }).click();
  await expect(homeState(page)).toContainText("总营业额 €175");
  await expect(homeState(page)).toContainText("营业状态：提前休息");
  await homeState(page).getByRole("link", { name: "修改今日台账" }).click();
  await page.getByRole("button", { name: "选择台账日期：2026年7月17日" }).click();
  const picker = page.getByRole("dialog", { name: "选择台账日期" });
  await expect(picker.getByRole("button", { name: "2026年7月18日" })).toBeDisabled();
  await picker.getByRole("button", { name: "昨天", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`date=${yesterday}$`));
  await expect(page.getByLabel("当日营业额", { exact: true })).toHaveValue("");
  await page.getByLabel("当日营业额", { exact: true }).fill("75");
  await page.getByLabel("状态", { exact: true }).selectOption("提前休息");
  await page.getByRole("button", { name: "补记历史记录", exact: true }).click();
  await waitForSaved(page);
  expect(flow.records.get(`1:${yesterday}`)).toMatchObject({ daily_revenue: 75, is_open: "提前休息" });
  await navigation(page, 390).getByRole("link", { name: "首页", exact: true }).click();
  await expect(homeState(page)).toContainText("总营业额 €175");
  await expect(homeState(page)).toContainText("营业状态：提前休息");
  await assertNoOverflow(page);
  expect(flow.contractErrors).toEqual([]);
});

test("date and store transitions require a choice before discarding unsaved amounts", async ({ page }) => {
  await page.clock.install({ time: new Date(`${today}T12:00:00Z`) });
  await page.setViewportSize({ width: 390, height: 844 });
  const flow = await mockHomeLedger(page);
  await page.goto("/");
  await homeState(page).getByRole("link", { name: "立即记账" }).click();
  await page.getByLabel(categories[0].name, { exact: true }).fill("123");
  const guard = page.getByRole("alertdialog", { name: "放弃未保存的修改？" });
  await page.getByRole("button", { name: "选择台账日期：2026年7月17日" }).click();
  await page.getByRole("dialog", { name: "选择台账日期" }).getByRole("button", { name: "昨天", exact: true }).click();
  await expect(guard).toBeVisible();
  await guard.getByRole("button", { name: "继续编辑" }).click();
  await expect(page).toHaveURL(new RegExp(`date=${today}$`));
  await expect(page.getByLabel(categories[0].name, { exact: true })).toHaveValue("123");
  await page.getByRole("button", { name: "选择台账日期：2026年7月17日" }).click();
  await page.getByRole("dialog", { name: "选择台账日期" }).getByRole("button", { name: "昨天", exact: true }).click();
  await guard.getByRole("button", { name: "放弃修改" }).click();
  await expect(page).toHaveURL(new RegExp(`date=${yesterday}$`));
  await expect(page.getByLabel(categories[0].name, { exact: true })).toHaveValue("");
  await page.getByLabel(categories[0].name, { exact: true }).fill("456");
  const store = page.getByTestId("mobile-store-picker").getByRole("combobox", { name: "门店" });
  await store.selectOption("2");
  await expect(guard).toBeVisible();
  await guard.getByRole("button", { name: "继续编辑" }).click();
  await expect(store).toHaveValue("1");
  await expect(page.getByLabel(categories[0].name, { exact: true })).toHaveValue("456");
  await store.selectOption("2");
  await guard.getByRole("button", { name: "放弃修改" }).click();
  await expect(store).toHaveValue("2");
  await expect(page.getByLabel(categories[0].name, { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("当日营业额", { exact: true })).toHaveValue("");
  expect(flow.attempts).toHaveLength(0);
  await page.getByLabel("当日营业额", { exact: true }).fill("77");
  await page.getByRole("button", { name: "补记历史记录", exact: true }).click();
  await waitForSaved(page);
  expect(flow.records.has(`1:${yesterday}`)).toBe(false);
  expect(flow.records.get(`2:${yesterday}`)).toMatchObject({ daily_revenue: 77 });
  await navigation(page, 390).getByRole("link", { name: "首页", exact: true }).click();
  await expect(homeState(page)).toContainText("今日尚未记录");
  await assertNoOverflow(page);
  expect(flow.contractErrors).toEqual([]);
});

test("a records-launched save retains additional input entered before its response", async ({ page }) => {
  await page.clock.install({ time: new Date(`${today}T12:00:00Z`) });
  await page.setViewportSize({ width: 390, height: 844 });
  const flow = await mockHomeLedger(page);
  await page.goto("/");
  await homeState(page).getByRole("link", { name: "立即记账" }).click();
  await page.getByLabel(categories[0].name, { exact: true }).fill("120");
  await page.getByRole("button", { name: "保存今日记录", exact: true }).click();
  await waitForSaved(page);
  await navigation(page, 390).getByRole("link", { name: "记录", exact: true }).click();
  await page.locator('main button[aria-label^="2026年7月17日"]').first().click();
  await page.getByRole("region", { name: `${today} 营业记录详情` }).getByRole("link", { name: "修改这天记录" }).click();
  await page.getByLabel(categories[0].name, { exact: true }).fill("150");
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route(`**/api/ledger/1/${today}`, async (route) => {
    if (route.request().method() === "PUT") await gate;
    await route.fallback();
  });
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  await expect(page.getByRole("button", { name: "保存中…" })).toBeDisabled();
  await page.getByLabel(categories[0].name, { exact: true }).fill("220");
  release();
  await expect.poll(() => flow.accepted.length).toBe(2);
  await expect(page).toHaveURL(new RegExp(`ledger\\?date=${today}$`));
  await expect(page.getByRole("button", { name: "保存修改", exact: true })).toBeEnabled();
  await expect(page.getByLabel(categories[0].name, { exact: true })).toHaveValue("220");
  await navigation(page, 390).getByRole("link", { name: "首页", exact: true }).click();
  await expect(page.getByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeVisible();
});

test("an archived store's homepage opens the recorded date without edit or delete actions", async ({ page }) => {
  await page.clock.install({ time: new Date(`${today}T12:00:00Z`) });
  await page.setViewportSize({ width: 390, height: 844 });
  await mockHomeLedger(page);
  await page.goto("/");
  await homeState(page).getByRole("link", { name: "立即记账" }).click();
  await page.getByLabel(categories[0].name, { exact: true }).fill("120");
  await page.getByRole("button", { name: "保存今日记录", exact: true }).click();
  await waitForSaved(page);
  await page.route("**/api/stores/accessible", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify([{ id: 1, name: "Archived synthetic store", timezone: "Europe/Berlin", is_active: false, wash_count_enabled: true }]) }));
  await page.goto("/");
  await homeState(page).getByRole("link", { name: "查看今日台账" }).click();
  const detail = page.getByRole("region", { name: `${today} 营业记录详情` });
  await expect(detail.getByText("€120", { exact: true }).first()).toBeVisible();
  await expect(detail.getByRole("link", { name: "修改这天记录" })).toHaveCount(0);
  await expect(detail.getByRole("button", { name: "删除记录" })).toHaveCount(0);
});
