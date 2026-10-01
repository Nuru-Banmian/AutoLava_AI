import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/release",
  reporter: [["line"], ["html", { open: "never", outputFolder: "playwright-report/release" }]],
  use: {
    baseURL: "https://127.0.0.1:8443",
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
