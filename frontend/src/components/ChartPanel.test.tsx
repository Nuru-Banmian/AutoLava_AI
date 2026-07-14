import { expect, it } from "vitest";
import { chartTooltipValue } from "@/components/ChartPanel";

it("uses the raw decimal string for chart tooltip money", () => {
  expect(chartTooltipValue({ revenue: Number.MAX_SAFE_INTEGER, revenue_raw: "9007199254740993.10" }, "revenue")).toBe("€9007199254740993.10");
});
