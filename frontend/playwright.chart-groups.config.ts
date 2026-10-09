import { defineConfig } from "@playwright/test";
import config from "./playwright.config";

export default defineConfig({ ...config, testDir: "./tests/release", testIgnore: [],
  testMatch: "agent-chart-groups.spec.ts", workers: 1 });
