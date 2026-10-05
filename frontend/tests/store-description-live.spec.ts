import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";

test.skip(!process.env.AUTOLAVA_DESCRIPTION_LIVE, "Use scripts/verify-issue-239-live.py with isolated SQLite");

async function login(page: Page, username = process.env.AUTOLAVA_LIVE_USERNAME!, password = process.env.AUTOLAVA_LIVE_PASSWORD!, navigate = true) {
  if (navigate) await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "首页", exact: true })).toBeVisible();
}

async function selectStore(page: Page, width: number, id: number, name: string) {
  if (width < 1024) {
    await page.getByRole("toolbar", { name: "门店列表操作" }).getByLabel("门店", { exact: true }).selectOption(String(id));
  } else {
    await page.getByRole("complementary", { name: "门店列表" }).getByRole("button", { name: new RegExp(name) }).click();
  }
}

for (const width of [390, 1280]) {
  test(`real description creation, editing, failure, conflict, clearing and draft guard at ${width}px`, async ({ page, context }) => {
    await page.setViewportSize({ width, height: 900 });
    await context.grantPermissions(["geolocation"]);
    await context.setGeolocation({ latitude: 45, longitude: 9 });
    await page.route("https://tile.openstreetmap.org/**", route => route.fulfill({ status: 204, body: "" }));
    await login(page);
    const other = await page.request.post("/api/admin/stores", { data: {
      name: `维修店-${width}`, address: "Synthetic address", latitude: 45, longitude: 9,
      description: "家电维修\n附近居民",
    } });
    expect(other.status()).toBe(201);
    const alternate = await other.json();
    await page.goto("/admin");
    await page.getByRole("button", { name: "新建门店", exact: true }).click();
    const create = page.getByRole("region", { name: "新建门店" });
    await create.getByLabel("门店名称", { exact: true }).fill(`烘焙店-${width}`);
    await create.getByLabel("门店描述", { exact: true }).fill("社区烘焙店\n主营面包与生日蛋糕");
    await create.getByRole("button", { name: "打开地图选择" }).click();
    await page.getByRole("button", { name: "确认位置", exact: true }).click();
    const createdResponse = page.waitForResponse(r => r.url().endsWith("/api/admin/stores") && r.request().method() === "POST");
    await create.getByRole("button", { name: "添加门店", exact: true }).click();
    const created = await (await createdResponse).json();
    expect(created.description).toBe("社区烘焙店\n主营面包与生日蛋糕");
    const details = page.getByRole("region", { name: "门店资料" });
    const description = details.getByLabel("门店描述", { exact: true });
    const save = details.getByRole("button", { name: "保存", exact: true });
    await expect(description).toHaveValue(created.description);
    const path = `/api/admin/stores/${created.id}`;

    await description.fill("😀".repeat(3000));
    await expect(details.getByText("3000 / 3000 字符", { exact: true })).toBeVisible();
    await expect(save).toBeEnabled();
    await description.fill("😀".repeat(3001));
    await expect(save).toBeDisabled();
    await description.fill("本地草稿\n生日蛋糕预约");
    // Inject only a transport failure; normal requests reach the real backend.
    await page.route(`**${path}`, async route => {
      if (route.request().method() === "PATCH") {
        await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "测试保存失败" }) });
      } else await route.continue();
    });
    await save.click();
    await expect(details.getByRole("alert")).toContainText("测试保存失败");
    await expect(description).toHaveValue("本地草稿\n生日蛋糕预约");
    await page.unroute(`**${path}`);
    const remote = await page.request.patch(path, { data: {
      description: "另一位管理员更新\n社区客群", expected_description_revision: 1,
    } });
    expect(remote.status()).toBe(200);
    await save.click();
    const review = details.getByRole("region", { name: "描述冲突核对" });
    await expect(review).toContainText("另一位管理员更新");
    await expect(description).toHaveValue("本地草稿\n生日蛋糕预约");
    await expect(save).toBeDisabled();
    await page.screenshot({ path: join(process.env.AUTOLAVA_DESCRIPTION_ARTIFACTS!, `conflict-${width}.png`), fullPage: true });
    await review.getByRole("button", { name: "已核对，保留草稿" }).click();
    const savedResponse = page.waitForResponse(r => r.url().endsWith(path) && r.request().method() === "PATCH");
    await save.click();
    expect((await (await savedResponse).json()).description_revision).toBe(3);
    await expect(save).toBeEnabled();

    await description.fill("未保存的切店草稿");
    await selectStore(page, width, alternate.id, alternate.name);
    const guard = page.getByRole("alertdialog", { name: "放弃未保存的修改？" });
    await expect(guard).toBeVisible();
    await guard.getByRole("button", { name: "继续编辑" }).click();
    await expect(description).toHaveValue("未保存的切店草稿");
    await selectStore(page, width, alternate.id, alternate.name);
    await guard.getByRole("button", { name: "放弃修改" }).click();
    await expect(description).toHaveValue("家电维修\n附近居民");
    await selectStore(page, width, created.id, created.name);
    await expect(description).toHaveValue("本地草稿\n生日蛋糕预约");
    await details.getByRole("button", { name: "清空描述" }).click();
    const clearResponse = page.waitForResponse(r => r.url().endsWith(path) && r.request().method() === "PATCH");
    await save.click();
    expect((await (await clearResponse).json()).description).toBe("");
    await expect(save).toBeEnabled();
    const listing = await (await page.request.get("/api/admin/stores")).json();
    expect(listing.find((store: { id: number }) => store.id === created.id).description).toBe("");
    expect(listing.find((store: { id: number }) => store.id === alternate.id).description).toBe("家电维修\n附近居民");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await page.screenshot({ path: join(process.env.AUTOLAVA_DESCRIPTION_ARTIFACTS!, `saved-${width}.png`), fullPage: true });
  });
}

test("real account switching protects drafts and isolates a delayed old save response", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await login(page);
  const store = await (await page.request.post("/api/admin/stores", { data: {
    name: "账号切换验收门店", address: "Synthetic address", latitude: 45, longitude: 9,
    description: "旧描述",
  } })).json();
  const username = `second-admin-${Date.now()}`;
  const password = "Synthetic-password239";
  expect((await page.request.post("/api/admin/users", { data: { username, password, role: "admin" } })).status()).toBe(201);
  await page.goto("/admin");
  await selectStore(page, 1280, store.id, store.name);
  const description = page.getByLabel("门店描述", { exact: true });
  await description.fill("账号切换草稿");
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  const guard = page.getByRole("alertdialog", { name: "放弃未保存的修改？" });
  await expect(guard).toBeVisible();
  await guard.getByRole("button", { name: "继续编辑" }).click();
  await expect(description).toHaveValue("账号切换草稿");
  let release!: () => void;
  let arrived!: () => void;
  let delivered!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const saved = new Promise<void>(resolve => { arrived = resolve; });
  const finished = new Promise<void>(resolve => { delivered = resolve; });
  const path = `/api/admin/stores/${store.id}`;
  await page.route(`**${path}`, async route => {
    const response = await route.fetch();
    arrived();
    await held;
    await route.fulfill({ response });
    delivered();
  });
  await page.getByRole("region", { name: "门店资料" }).getByRole("button", { name: "保存", exact: true }).click();
  await saved;
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await guard.getByRole("button", { name: "放弃修改" }).click();
  await expect(page.getByRole("button", { name: "登录", exact: true })).toBeVisible();
  await login(page, username, password, false);
  await page.getByRole("navigation", { name: "主导航", exact: true }).getByRole("link", { name: "管理中心" }).click();
  await selectStore(page, 1280, store.id, store.name);
  await expect(description).toHaveValue("账号切换草稿");
  await description.fill("新管理员未保存草稿");
  release();
  await finished;
  await page.unroute(`**${path}`);
  await expect(description).toHaveValue("新管理员未保存草稿");
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(guard).toBeVisible();
});
