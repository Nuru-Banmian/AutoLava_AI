import type { FullResult, Reporter, TestCase, TestResult } from "@playwright/test/reporter";

export default class RequirePassed implements Reporter {
  private count = 0;
  private incomplete = false;
  private serverError = false;

  onStdErr(chunk: string | Buffer) {
    if (/ERROR \[|Traceback \(most recent call last\)/.test(chunk.toString())) this.serverError = true;
  }

  onTestEnd(test: TestCase, result: TestResult) {
    this.count++;
    if (result.status !== "passed" || test.expectedStatus !== "passed") this.incomplete = true;
  }

  async onEnd(result: FullResult): Promise<{ status: FullResult["status"] }> {
    if (!this.count || this.incomplete || this.serverError || result.status !== "passed") {
      console.error("Acceptance requires passed tests and no server errors; skips/expected failures are rejected.");
      return { status: "failed" };
    }
    return { status: "passed" };
  }
}
