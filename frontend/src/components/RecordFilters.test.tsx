import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecordFilters } from "@/components/RecordFilters";

describe("RecordFilters", () => {
  it("emits full calendar preset ranges and exports the current range", () => {
    const onChange = vi.fn();
    const onExport = vi.fn();

    render(<RecordFilters mode="current-month" range={{ start: "2026-07-01", end: "2026-07-31" }} today="2026-07-17" exporting={false} exportError="" onChange={onChange} onExport={onExport} />);

    expect(screen.getByLabelText("日期范围预设")).toHaveClass("grid", "grid-cols-3");
    expect(screen.getByTestId("record-filter-dates")).toHaveClass("grid", "grid-cols-2");
    for (const name of ["本月", "上月", "自定义", "导出当前范围"]) {
      expect(screen.getByRole("button", { name })).toHaveClass("h-10");
    }
    expect(screen.getByRole("button", { name: "导出当前范围" })).toHaveClass("w-full");
    expect(screen.getByRole("button", { name: "本月" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "上月" }));
    expect(onChange).toHaveBeenCalledWith("previous-month", { start: "2026-06-01", end: "2026-06-30" });
    fireEvent.click(screen.getByRole("button", { name: "导出当前范围" }));
    expect(onExport).toHaveBeenCalledOnce();
  });

  it("only emits valid custom ranges and exposes export status", () => {
    const onChange = vi.fn();
    render(<RecordFilters mode="custom" range={{ start: "2026-07-01", end: "2026-07-31" }} today="2026-07-17" exporting exportError="导出失败，请重试" onChange={onChange} onExport={vi.fn()} />);

    expect(screen.getByLabelText("开始日期")).toHaveClass("h-10", "min-w-0", "pr-10");
    expect(screen.getByLabelText("结束日期")).toHaveClass("h-10", "min-w-0", "pr-10");
    fireEvent.change(screen.getByLabelText("开始日期"), { target: { value: "2026-07-18" } });
    fireEvent.change(screen.getByLabelText("结束日期"), { target: { value: "2026-07-17" } });
    fireEvent.click(screen.getByRole("button", { name: "自定义" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "导出当前范围" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("导出失败，请重试");
  });
});
