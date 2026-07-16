import { expect, test, type Locator, type Page } from "@playwright/test";

const categories = [
  { id: 1, name: "现金", include_in_total: true, is_active: true, sort_order: 1 },
  { id: 2, name: "刷卡", include_in_total: true, is_active: true, sort_order: 2 },
];

function berlinToday() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Berlin", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function snapshot(date: string, amount: string) {
  const now = `${date}T12:00:00`;
  return {
    id: 41, store_id: 1, date, daily_revenue: amount, wash_count: null, is_open: "营业",
    income_mode: "composed", income_config_version_id: 4, row_version: 1,
    weather: null, weather_auto: null, weather_code: null, temperature_max: null,
    temperature_min: null, precipitation: null, activity: null, weather_edited: false,
    scanned: false, created_by: 1, updated_by: 1, created_at: now, updated_at: now,
    items: [
      { id: 101, category_id: 1, category_name: "现金", include_in_total: true, sort_order: 1, amount, created_at: now, updated_at: now },
      { id: 102, category_id: 2, category_name: "刷卡", include_in_total: true, sort_order: 2, amount: "0.00", created_at: now, updated_at: now },
    ],
  };
}

async function mockDailyApi(page: Page) {
  const today = berlinToday();
  let savedRecord: ReturnType<typeof snapshot> | null = null;
  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });

    if (path === "/api/auth/me") return json({ id: 1, username: "administrator", role: "admin" });
    if (path === "/api/stores/accessible") return json([{ id: 1, name: "Berlin", timezone: "Europe/Berlin" }]);
    if (path === "/api/dashboard/1") return json([
      { card_type: "yesterday", state: "missing", revenue: null, weather: null, weekday: null, temperature_max: null, temperature_min: null, precipitation: null, hint: null, generated_at: `${today}T08:00:00` },
      { card_type: "today", state: savedRecord ? "recorded" : "missing", revenue: savedRecord?.daily_revenue ?? null, weather: "晴", weekday: null, temperature_max: null, temperature_min: null, precipitation: null, hint: null, generated_at: `${today}T08:00:00` },
      { card_type: "tomorrow", state: "forecast", revenue: null, weather: "多云", weekday: "星期五", temperature_max: "24", temperature_min: "16", precipitation: "0", hint: "适合营业", generated_at: `${today}T08:00:00` },
    ]);
    if (path === "/api/income-config/1/current") return json({ store_id: 1, version_id: 4, version: 4, enabled: true, formula: "现金 + 刷卡", created_at: `${today}T08:00:00`, items: categories.map((category, index) => ({ id: index + 10, category_id: category.id, ...category })) });
    if (path === "/api/weather/1/" + today) return json({ weather: null, weather_code: null, temperature_max: null, temperature_min: null, precipitation: null });
    if (path === "/api/ledger/1/recent") return json(savedRecord ? [savedRecord] : []);
    if (path === "/api/ledger/1/" + today && request.method() === "GET") return savedRecord ? json(savedRecord) : json({ detail: "not found" }, 404);
    if (path === "/api/ledger/1/" + today && request.method() === "PUT") {
      const body = request.postDataJSON() as { items: { category_id: number; amount: string }[] };
      const amount = body.items.find((item) => item.category_id === 1)?.amount ?? "0.00";
      savedRecord = snapshot(today, amount);
      return json({ id: 41, date: today, daily_revenue: amount, row_version: 1 });
    }
    if (path === "/api/database/1/records") {
      const inRange = savedRecord && url.searchParams.get("start")! <= today && url.searchParams.get("end")! >= today;
      return json({ items: inRange ? [savedRecord] : [], categories, sum_daily_revenue: inRange ? savedRecord.daily_revenue : "0.00", total: inRange ? 1 : 0, page: 1, page_size: Number(url.searchParams.get("page_size") ?? 31) });
    }
    if (path === "/api/charts/1") return json({
      kpis: { total_revenue: savedRecord?.daily_revenue ?? "0.00", record_days: savedRecord ? 1 : 0, open_days: savedRecord ? 1 : 0, average_revenue: savedRecord?.daily_revenue ?? "0.00", primary_categories: [], total_wash_count: null, average_ticket: null },
      daily: savedRecord ? [{ date: today, revenue: savedRecord.daily_revenue }] : [],
      categories: savedRecord ? [{ category_id: 1, category_name: "现金", amount: savedRecord.daily_revenue }, { category_id: 2, category_name: "刷卡", amount: "0.00" }] : [],
      monthly: [], weather: [], weekday: [],
    });
    return json({ detail: `unmocked ${request.method()} ${path}` }, 500);
  });
  return today;
}

async function expectNoHorizontalScroll(page: Page) {
  await expect.poll(() => page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) <= window.innerWidth)).toBe(true);
}

async function expectPageEndClear(page: Page, sentinel: Locator) {
  const navigation = page.getByRole("navigation", { name: "移动导航" });
  await expect(navigation).toBeVisible();
  await expect(sentinel).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect.poll(() => page.evaluate(() => {
    const maximum = document.documentElement.scrollHeight - window.innerHeight;
    return Math.abs(maximum - window.scrollY);
  })).toBeLessThanOrEqual(1);
  const [content, bar] = await Promise.all([sentinel.boundingBox(), navigation.boundingBox()]);
  expect(content).not.toBeNull();
  expect(bar).not.toBeNull();
  expect(content!.y + content!.height).toBeLessThanOrEqual(bar!.y);
}

for (const viewport of [{ name: "desktop", width: 1280, height: 900 }, { name: "320px", width: 320, height: 700 }]) {
  test(`${viewport.name}: home to ledger to history to analytics`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const today = await mockDailyApi(page);
    await page.goto("/");

    await expect(page.getByRole("heading", { name: /^(昨日|今日|明日)$/ })).toHaveCount(3);
    await expect(page.getByText("昨日尚未记录")).toBeVisible();
    await expect(page.getByText("今日尚未记账")).toBeVisible();
    await expect(page.getByRole("heading", { name: "明日" })).toBeVisible();
    await expect(page.getByText("尚未记账")).toHaveCount(1);
    await page.getByRole("link", { name: "立即记账" }).click();
    await expect(page).toHaveURL(new RegExp(`/ledger\\?date=${today}$`));

    await page.getByLabel("现金").fill("100");
    await page.getByRole("button", { name: "保存今日记录" }).click();
    await expect(page.getByRole("status")).toContainText("保存成功");
    await expectNoHorizontalScroll(page);
    if (viewport.width === 320) {
      await expectPageEndClear(page, page.getByRole("heading", { name: "最近七天" }).locator(".."));
    }

    const navigation = viewport.width === 320
      ? page.getByRole("navigation", { name: "移动导航" })
      : page.getByRole("navigation", { name: "主导航" });
    await navigation.getByRole("link", { name: viewport.width === 320 ? "记录" : "历史记录" }).click();
    await expect(page.getByRole("searchbox")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "补记一天", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /已有记录/ })).toBeVisible();
    await page.getByRole("button", { name: /已有记录/ }).click();
    const [year, month, day] = today.split("-").map(Number);
    const detail = page.getByRole("heading", { name: `${year}年${month}月${day}日` }).locator("xpath=../..");
    await expect(detail.getByText("营业额", { exact: true }).locator("..").getByText("€100.00", { exact: true })).toBeVisible();
    await expect(detail.getByRole("link", { name: "修改这天记录" })).toBeVisible();
    await expectNoHorizontalScroll(page);
    if (viewport.width === 320) await expectPageEndClear(page, detail);

    if (viewport.width === 320) {
      await navigation.getByRole("link", { name: "更多" }).click();
      await page.getByRole("navigation", { name: "更多功能" }).getByRole("link", { name: "经营分析" }).click();
    } else {
      await navigation.getByRole("link", { name: "经营分析" }).click();
    }
    const week = page.getByRole("button", { name: "最近 7 天" });
    const monthPreset = page.getByRole("button", { name: "本月" });
    const custom = page.getByRole("button", { name: "自定义日期" });
    await expect(week).toBeVisible();
    await expect(monthPreset).toHaveAttribute("aria-pressed", "true");
    await expect(custom).toBeVisible();
    await week.click();
    await expect(week).toHaveAttribute("aria-pressed", "true");
    await expect(monthPreset).toHaveAttribute("aria-pressed", "false");
    await monthPreset.click();
    await expect(monthPreset).toHaveAttribute("aria-pressed", "true");
    await custom.click();
    await expect(custom).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByLabel("图表开始日期")).toBeVisible();
    await expect(page.getByLabel("图表结束日期")).toBeVisible();
    await expect(page.getByRole("heading", { name: "营业额趋势" })).toBeVisible();
    await expect(page.getByText("€100.00").first()).toBeVisible();
    await expectNoHorizontalScroll(page);
    if (viewport.width === 320) {
      const chartEnd = page.getByRole("heading", { name: "收入构成" }).locator("xpath=../..");
      await expectPageEndClear(page, chartEnd);
    }
  });
}
