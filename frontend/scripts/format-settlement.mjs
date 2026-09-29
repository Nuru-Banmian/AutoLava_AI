import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const mode = process.argv.includes("--write") ? "--write" : "--check";
const result = spawnSync(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["--yes", "prettier@3.6.2", mode, "src/pages/CompanySettlementPage.tsx"],
  { cwd: root, stdio: "inherit", shell: process.platform === "win32" },
);

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
