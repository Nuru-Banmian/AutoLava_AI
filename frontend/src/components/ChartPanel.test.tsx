import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ChartPanel, chartSeriesColors, chartTooltipValue } from "@/components/ChartPanel";

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

it("uses the default plot height and accepts a height override", () => {
  const { rerender } = render(
    <ChartPanel title="趋势" kind="line" data={[{ label: "7月", revenue: 10 }]} xKey="label" valueKey="revenue" />,
  );

  expect(screen.getByTestId("chart-panel-plot")).toHaveClass("h-72", "min-h-72");

  rerender(
    <ChartPanel title="趋势" kind="line" data={[{ label: "7月", revenue: 10 }]} xKey="label" valueKey="revenue" heightClassName="h-64 min-h-64" />,
  );

  expect(screen.getByTestId("chart-panel-plot")).toHaveClass("h-64", "min-h-64");
});

it("renders embedded charts without a card wrapper", () => {
  render(
    <ChartPanel
      embedded
      title="营业额趋势"
      kind="line"
      data={[{ label: "7月1日", revenue: 100, revenue_raw: "100.00" }]}
      xKey="label"
      valueKey="revenue"
    />,
  );

  expect(screen.getByRole("heading", { name: "营业额趋势" })).toBeInTheDocument();
  expect(screen.getByTestId("chart-panel-content").closest("[data-slot='card']")).toBeNull();
});
