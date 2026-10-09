import { defineConfig } from "@playwright/test";

const python = process.env.ACCEPTANCE_PYTHON;

export default defineConfig({
  testDir: "./acceptance",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [["line"], ["html", { open: "never", outputFolder: "acceptance-report" }],
             ["./acceptance/require-passed.ts"]],
  outputDir: "acceptance-results",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { browserName: "chromium", viewport: { width: 1440, height: 900 } } },
    { name: "narrow", use: { browserName: "chromium", viewport: { width: 390, height: 844 } } },
  ],
  webServer: [
    {
      command: python ? `"${python}" -m acceptance.server` : "uv run --frozen python -m acceptance.server",
      cwd: "../backend",
      url: "http://127.0.0.1:8000/ready",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm exec vite preview -- --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://127.0.0.1:4173/login",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
