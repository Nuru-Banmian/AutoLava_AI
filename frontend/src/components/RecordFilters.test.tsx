import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecordFilters } from "@/components/RecordFilters";

describe("RecordFilters", () => {
  const props = {
    mode: "current-month" as const,
    range: { start: "2026-07-01", end: "2026-07-17" },
    today: "2026-07-17",
    exporting: false,
    exportError: "",
    onChange: vi.fn(),
    onExport: vi.fn(),
  };

  it("emits full calendar preset ranges and exports the current range", () => {
    const onChange = vi.fn();
    const onExport = vi.fn();

    render(<RecordFilters mode="current-month" range={{ start: "2026-07-01", end: "2026-07-31" }} today="2026-07-17" exporting={false} exportError="" onChange={onChange} onExport={onExport} />);

    expect(screen.getByLabelText("日期范围预设")).toHaveClass("grid", "grid-cols-3");
    for (const name of ["本月", "上月", "自定义", "导出当前范围"]) {
      expect(screen.getByRole("button", { name })).toHaveClass("min-h-11");
    }
    expect(screen.getByRole("button", { name: "导出当前范围" })).toHaveClass("w-full");
    expect(screen.getByRole("button", { name: "本月" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "上月" }));
    expect(onChange).toHaveBeenCalledWith("previous-month", { start: "2026-06-01", end: "2026-06-30" });
    fireEvent.click(screen.getByRole("button", { name: "导出当前范围" }));
    expect(onExport).toHaveBeenCalledOnce();
  });

  it("reveals custom dates on demand and hides them after selecting a preset", () => {
    const view = render(<RecordFilters {...props} />);

    expect(screen.queryByTestId("record-filter-dates")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "自定义" }));
    expect(screen.getByTestId("record-filter-dates")).toHaveClass("grid", "grid-cols-2");
    expect(screen.getByLabelText("开始日期")).toHaveClass("h-10", "min-w-0", "pr-10");
    expect(props.onChange).toHaveBeenCalledWith("custom", props.range);

    fireEvent.click(screen.getByRole("button", { name: "上月" }));
    expect(screen.queryByTestId("record-filter-dates")).not.toBeInTheDocument();
    expect(props.onChange).toHaveBeenLastCalledWith("previous-month", {
      start: "2026-06-01",
      end: "2026-06-30",
    });

    view.rerender(<RecordFilters {...props} mode="custom" />);
    expect(screen.getByTestId("record-filter-dates")).toBeInTheDocument();
  });

  it("preserves an open invalid custom draft across value-equivalent preset range updates", () => {
    const onChange = vi.fn();
    const view = render(<RecordFilters {...props} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "自定义" }));
    fireEvent.change(screen.getByLabelText("开始日期"), { target: { value: "2026-07-18" } });

    view.rerender(<RecordFilters {...props} onChange={onChange} range={{ start: "2026-07-01", end: "2026-07-17" }} />);

    expect(screen.getByTestId("record-filter-dates")).toBeInTheDocument();
    expect(screen.getByLabelText("开始日期")).toHaveValue("2026-07-18");
    expect(screen.getByLabelText("结束日期")).toHaveValue("2026-07-17");
  });

  it("hides custom dates when external mode changes from custom to a preset", () => {
    const view = render(<RecordFilters {...props} mode="custom" />);

    expect(screen.getByTestId("record-filter-dates")).toBeInTheDocument();
    view.rerender(<RecordFilters {...props} mode="current-month" />);
    expect(screen.queryByTestId("record-filter-dates")).not.toBeInTheDocument();
  });

  it("only emits valid custom ranges and exposes export status", () => {
    const onChange = vi.fn();
    render(<RecordFilters mode="current-month" range={{ start: "2026-07-01", end: "2026-07-17" }} today="2026-07-17" exporting exportError="导出失败，请重试" onChange={onChange} onExport={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "自定义" }));
    expect(screen.getByLabelText("开始日期")).toHaveClass("h-10", "min-w-0", "pr-10");
    expect(screen.getByLabelText("结束日期")).toHaveClass("h-10", "min-w-0", "pr-10");
    fireEvent.change(screen.getByLabelText("开始日期"), { target: { value: "2026-07-18" } });
    fireEvent.change(screen.getByLabelText("结束日期"), { target: { value: "2026-07-17" } });
    fireEvent.click(screen.getByRole("button", { name: "自定义" }));

    expect(screen.getByTestId("record-filter-dates")).toBeInTheDocument();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "导出当前范围" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("导出失败，请重试");
  });

  it("does not emit a custom range that ends after today", () => {
    const onChange = vi.fn();
    render(<RecordFilters {...props} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "自定义" }));
    onChange.mockClear();
    fireEvent.change(screen.getByLabelText("结束日期"), { target: { value: "2026-07-18" } });

    expect(onChange).not.toHaveBeenCalled();
  });
});
