import { defineConfig } from "@playwright/test";
export default defineConfig({ globalSetup: "./tests/global-setup.ts", testDir: "./tests", reporter: "line", use: { baseURL: "http://127.0.0.1:4173" } });
