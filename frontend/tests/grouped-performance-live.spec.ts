import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";

test.skip(!process.env.AUTOLAVA_GROUPS_MANIFEST, "Run using scripts/verify-issue-227-live.py with disposable migrated SQLite");

type Group = { average_revenue: number; operating_day_count: number };
type Scope = {
  store_id: number; month: string;
  expected: { weekday: (Group & { weekday: number })[]; weather: (Group & { weather: string })[] };
};
type Manifest = { stores: { id: number; name: string }[]; scopes: Scope[] };
const weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const euro = (value: number) => `€${new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 }).format(value)}`;

function reading(label: string, group?: Group) {
  return group ? `${label}：${euro(group.average_revenue)}，${group.operating_day_count} 天经营日样本` : `${label}：无经营日样本，—，0 天`;
}

function manifest(): Manifest {
  return JSON.parse(readFileSync(process.env.AUTOLAVA_GROUPS_MANIFEST!, "utf8")) as Manifest;
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("用户名").fill(process.env.AUTOLAVA_LIVE_USERNAME!);
  await page.getByLabel("密码", { exact: true }).fill(process.env.AUTOLAVA_LIVE_PASSWORD!);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "首页", exact: true })).toBeVisible();
  await page.goto("/database");
  await page.getByRole("button", { name: "经营分析", exact: true }).click();
}

async function selectScope(page: Page, width: number, scope: Scope) {
  const picker = page.getByTestId(width < 768 ? "mobile-store-picker" : "desktop-store-picker").getByLabel("门店");
  await picker.selectOption(String(scope.store_id));
  const month = page.getByRole("region", { name: "记录筛选" }).getByLabel("月份", { exact: true });
  await month.fill(scope.month);
  await expect(page.getByText(new RegExp(`当前区间：${scope.month}-01 至 ${scope.month}-(30|31)`))).toBeVisible();
}

async function assertScope(page: Page, scope: Scope) {
  const days = page.getByRole("region", { name: "星期经营表现", exact: true });
  const weather = page.getByRole("region", { name: "天气与营业额对比", exact: true });
  const dayLabels = weekdays.map((label, day) => reading(label, scope.expected.weekday.find((row) => row.weekday === day)));
  const weatherLabels = scope.expected.weather.map((row) => reading(row.weather, row));
  await expect(days.getByRole("listitem")).toHaveCount(7);
  await expect(weather.getByRole("listitem")).toHaveCount(weatherLabels.length);
  await expect.poll(() => days.getByRole("listitem").evaluateAll((elements) => elements.map((element) => element.getAttribute("aria-label")))).toEqual(dayLabels);
  await expect.poll(() => weather.getByRole("listitem").evaluateAll((elements) => elements.map((element) => element.getAttribute("aria-label")))).toEqual(weatherLabels);
  for (const card of [days, weather]) {
    const firstRow = await rect(card.getByRole("listitem").first());
    expect(firstRow.height).toBeLessThanOrEqual(36);
    await expect(card.getByRole("combobox")).toHaveCount(0);
    await expect(card.locator("footer")).toHaveCount(0);
  }
  await expect(page.getByText("分组比较仅反映已记录经营日，不表示因果关系或预测。", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("日历读数日期")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^查看 .* 每日台账$/ })).toHaveCount(0);
  return { days, weather };
}

async function rect(locator: Locator) {
  const bounds = await locator.boundingBox();
  if (!bounds) throw new Error("Expected real browser geometry");
  return bounds;
}

for (const width of [320, 390, 768, 1024, 1280]) {
  test(`${width}px: real API amounts, sample counts, fixed ordering, natural height and accessible grouped readings`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const data = manifest();
    await login(page);
    await selectScope(page, width, data.scopes[0]);
    const { days, weather } = await assertScope(page, data.scopes[0]);
    const firstDayRow = days.getByRole("listitem").first();
    await firstDayRow.focus();
    await expect(firstDayRow).toBeFocused();
    await firstDayRow.press("Tab");
    await expect(days.getByRole("listitem").nth(1)).toBeFocused();
    const longWeather = weather.getByRole("listitem", { name: /^雷雨伴大冰雹：/ });
    await longWeather.hover();
    await expect(longWeather).toHaveAttribute("title", reading("雷雨伴大冰雹", data.scopes[0].expected.weather.find((row) => row.weather === "雷雨伴大冰雹")));
    const longLabel = await rect(longWeather.locator("span").first());
    const longRow = await rect(longWeather);
    expect(longLabel.x).toBeGreaterThanOrEqual(longRow.x);
    expect(longLabel.x + longLabel.width).toBeLessThanOrEqual(longRow.x + longRow.width);
    const dayCard = await rect(days);
    const weatherCard = await rect(weather);
    const firstDay = await rect(days.getByRole("listitem").first());
    const firstWeather = await rect(weather.getByRole("listitem").first());
    if (width >= 1024) {
      expect(Math.abs(dayCard.y - weatherCard.y)).toBeLessThanOrEqual(1);
      expect(Math.abs(dayCard.height - weatherCard.height)).toBeLessThanOrEqual(1);
      expect(Math.abs(firstDay.y - firstWeather.y)).toBeLessThanOrEqual(1);
    } else {
      expect(weatherCard.y).toBeGreaterThan(dayCard.y + dayCard.height);
      expect(weatherCard.height).toBeGreaterThan(dayCard.height + 500);
      const lastDay = await rect(days.getByRole("listitem").last());
      expect(dayCard.y + dayCard.height - lastDay.y - lastDay.height).toBeLessThan(30);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    const calendar = page.getByRole("region", { name: "营业日历", exact: true });
    const calendarBounds = await rect(calendar);
    expect(calendarBounds.width).toBeLessThanOrEqual(420);
    if (width >= 1024) {
      const cell = await rect(calendar.getByRole("button").first());
      expect(Math.abs(cell.width - cell.height)).toBeLessThanOrEqual(3);
      const composition = page.getByRole("region", { name: "收入构成", exact: true });
      if (await composition.count()) {
        const compositionBounds = await rect(composition);
        expect(Math.abs(compositionBounds.y - calendarBounds.y)).toBeLessThanOrEqual(1);
        expect(compositionBounds.x + compositionBounds.width).toBeLessThan(calendarBounds.x);
      }
      await calendar.locator("..").screenshot({ path: join(process.env.AUTOLAVA_GROUPS_ARTIFACTS!, `analysis-bottom-${width}.png`), animations: "disabled" });
    }
    writeFileSync(join(process.env.AUTOLAVA_GROUPS_ARTIFACTS!, `geometry-${width}.json`), JSON.stringify({ width, dayCard, weatherCard, firstDay, firstWeather, pageHeight: await page.evaluate(() => document.documentElement.scrollHeight) }, null, 2));
    await page.screenshot({ path: join(process.env.AUTOLAVA_GROUPS_ARTIFACTS!, `dense-${width}.png`), fullPage: true, animations: "disabled" });
    if (width === 390 || width === 1280) {
      await days.locator("..").locator("..").screenshot({ path: join(process.env.AUTOLAVA_GROUPS_ARTIFACTS!, `grouped-dense-${width}.png`), animations: "disabled" });
    }

    await selectScope(page, width, data.scopes[1]);
    await assertScope(page, data.scopes[1]);
    await selectScope(page, width, data.scopes[2]);
    const sparse = await assertScope(page, data.scopes[2]);
    if (width >= 1024) {
      expect(Math.abs((await rect(sparse.days)).height - (await rect(sparse.weather)).height)).toBeLessThanOrEqual(1);
    }
    await expect(sparse.days.getByRole("listitem", { name: "周三：无经营日样本，—，0 天", exact: true })).toBeVisible();
    await expect(sparse.days.getByRole("listitem", { name: "周二：€0，1 天经营日样本", exact: true })).toBeVisible();
    await expect(sparse.weather.getByRole("listitem", { name: "未记录：€203，2 天经营日样本", exact: true })).toBeVisible();
    await page.screenshot({ path: join(process.env.AUTOLAVA_GROUPS_ARTIFACTS!, `sparse-${width}.png`), fullPage: true, animations: "disabled" });
    if (width === 390 || width === 1280) {
      await sparse.days.locator("..").locator("..").screenshot({ path: join(process.env.AUTOLAVA_GROUPS_ARTIFACTS!, `grouped-sparse-${width}.png`), animations: "disabled" });
    }
    await selectScope(page, width, data.scopes[0]);
    await assertScope(page, data.scopes[0]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
}

test("390px: amounts stay visible without readers and calendar dates open directly by touch", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, hasTouch: true });
  const page = await context.newPage();
  try {
    await login(page);
    const scope = manifest().scopes[0];
    await selectScope(page, 390, scope);
    const { weather } = await assertScope(page, scope);
    const missing = weather.getByRole("listitem", { name: "未记录：€0，1 天经营日样本", exact: true });
    await missing.tap();
    await expect(missing).toHaveText("未记录€01 天");
    await page.getByRole("button", { name: "2026-07-31 提前休息 €0", exact: true }).tap();
    await expect(page.getByRole("region", { name: "2026-07-31 营业记录详情", exact: true })).toBeVisible();
  } finally {
    await context.close();
  }
});
