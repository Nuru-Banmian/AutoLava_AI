import { defineConfig } from "@playwright/test";
import config from "./playwright.config";

// Real backend acceptance is opt-in; ordinary frontend CI uses controlled API routes.
export default defineConfig({ ...config, testDir: "./tests/release", testIgnore: [],
  testMatch: "agent-charts.spec.ts", workers: 1 });
