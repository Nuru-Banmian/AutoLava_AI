import { expect, it } from "vitest";
import { chartSeriesColors, chartTooltipValue } from "@/components/ChartPanel";

it("uses the raw decimal string for chart tooltip money", () => {
  expect(chartTooltipValue({ revenue: Number.MAX_SAFE_INTEGER, revenue_raw: "9007199254740993.10" }, "revenue")).toBe("€9007199254740993.10");
});

it("uses theme variables for chart series", () => {
  expect(chartSeriesColors).toEqual([
    "var(--primary)",
    "var(--chart-series-2)",
    "var(--chart-series-3)",
  ]);
});
