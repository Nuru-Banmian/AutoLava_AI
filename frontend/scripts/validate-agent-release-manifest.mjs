import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifestPath = resolve(
  frontendRoot,
  "..",
  "backend",
  "tests",
  "release",
  "agent_release_cases.json",
);
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const require = createRequire(import.meta.url);
const playwrightCli = require.resolve("@playwright/test/cli");
const collection = spawnSync(
  process.execPath,
  [playwrightCli, "test", "--list"],
  {
    cwd: frontendRoot,
    encoding: "utf8",
  },
);

if (collection.status !== 0) {
  process.stderr.write(collection.stderr || collection.stdout);
  process.exit(collection.status ?? 1);
}

const collectedTests = new Set();
for (const line of collection.stdout.split(/\r?\n/)) {
  const match = line.match(/^\s*(.+?):\d+:\d+ › (.+)$/);
  if (match) {
    collectedTests.add(`${basename(match[1])}\0${match[2]}`);
  }
}

const missing = [];
let declaredCount = 0;
for (const releaseCase of manifest.frontend_cases) {
  if (
    !Array.isArray(releaseCase.test_titles) ||
    releaseCase.test_titles.length === 0 ||
    releaseCase.test_titles.some(
      (title) => typeof title !== "string" || title.length === 0,
    )
  ) {
    missing.push(`${releaseCase.id}: test_titles must be non-empty strings`);
    continue;
  }
  for (const title of releaseCase.test_titles) {
    declaredCount += 1;
    const key = `${basename(releaseCase.test_file)}\0${title}`;
    if (!collectedTests.has(key)) {
      missing.push(`${releaseCase.test_file} › ${title}`);
    }
  }
}

if (missing.length > 0) {
  process.stderr.write(
    `Agent release manifest references uncollected Playwright tests:\n${missing
      .map((item) => `- ${item}`)
      .join("\n")}\n`,
  );
  process.exit(1);
}

process.stdout.write(
  `Validated ${declaredCount} Agent release Playwright tests against the actual collection.\n`,
);
