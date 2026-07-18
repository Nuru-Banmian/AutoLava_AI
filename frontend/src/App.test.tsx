import { render, screen, within } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { buttonVariants } from "./components/ui/button";
import App, { Application } from "./App";
import { createAppRouter } from "./router";

const applicationStyles = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

const server = setupServer(
  http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "admin", role: "admin", is_owner: false })),
  http.get("/api/stores/accessible", () => HttpResponse.json([
    { id: 1, name: "总店", timezone: "Europe/Berlin" },
    { id: 2, name: "二店", timezone: "Europe/Berlin" },
  ])),
  http.get("/api/admin/stores", () => HttpResponse.json([])),
  http.get("/api/dashboard/:storeId", () => HttpResponse.json([])),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderApplication(path: string, options: { role?: "admin" | "user" } = {}) {
  if (options.role) {
    server.use(http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: options.role, role: options.role, is_owner: false })));
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

  it("shows four mobile entries and hides management from regular users", async () => {
    renderApplication("/more", { role: "user" });
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
    renderApplication("/more", { role: "user" });

    const desktopPicker = await screen.findByTestId("desktop-store-picker");
    const select = within(desktopPicker).getByRole("combobox", { name: "门店" });
    expect(await within(select).findByRole("option", { name: storeName })).toBeInTheDocument();
    expect(select).toHaveClass("min-w-0", "max-w-full", "flex-1");
    expect(select.closest("label")).toHaveClass("min-w-0", "max-w-full");
    expect(select.closest("label")?.parentElement).toHaveClass("min-w-0", "max-w-full");
    expect(select.closest("label")?.parentElement?.parentElement).toHaveClass("min-w-0", "max-w-full");
  });

  it("moves the global store selector out of More and into the shell", async () => {
    renderApplication("/more", { role: "user" });
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
    const view = renderApplication("/admin", { role: "admin" });
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
    renderApplication("/more", { role: "admin" });
    const more = await screen.findByRole("navigation", { name: "更多功能" });
    expect(within(more).getByRole("link", { name: "管理中心" })).toHaveAttribute("href", "/admin");
    expect(within(more).getByRole("link", { name: "系统状态" })).toHaveAttribute("href", "/admin?tab=status");
  });

  it("keeps the administrator desktop sidebar in the required order", async () => {
    renderApplication("/", { role: "admin" });
    const nav = await screen.findByRole("navigation", { name: "主导航" });
    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "首页",
      "每日记账",
      "营业记录",
      "管理中心",
    ]);
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
