import { defineConfig } from "@playwright/test";
import config from "./playwright.config";

export default defineConfig({ ...config, testDir: "./tests/release", testIgnore: [],
  testMatch: "agent-saved-charts.spec.ts", workers: 1, timeout: 120000 });
