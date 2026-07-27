import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const source = resolve(process.argv[2] ?? "playwright-results.xml");
const destination = resolve(process.argv[3] ?? "redacted-diagnostics/playwright-summary.json");

let xml = "";
try {
  xml = await readFile(source, "utf8");
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}

const count = (pattern) => [...xml.matchAll(pattern)].length;
const summary = {
  schema_version: 1,
  suites: count(/<testsuite\b/g),
  tests: count(/<testcase\b/g),
  failures: count(/<(?:failure|error)\b/g),
  skipped: count(/<skipped\b/g),
  generated_from_redacted_fields_only: true,
};

await mkdir(dirname(destination), { recursive: true });
await writeFile(destination, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
