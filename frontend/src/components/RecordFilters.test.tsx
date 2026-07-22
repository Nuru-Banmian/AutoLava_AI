import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecordFilters } from "@/components/RecordFilters";

describe("RecordFilters", () => {
  const props = {
    mode: "month" as const,
    range: { start: "2026-07-01", end: "2026-07-31" },
    today: "2026-07-17",
    exporting: false,
    exportError: "",
    onChange: vi.fn(),
    onExport: vi.fn(),
  };

  it("navigates full calendar months and exports the current range", () => {
    const onChange = vi.fn();
    const onExport = vi.fn();
    render(<RecordFilters {...props} onChange={onChange} onExport={onExport} />);

    expect(screen.getByLabelText("月份导航")).toHaveClass("grid");
    expect(screen.getByLabelText("月份")).toHaveAttribute("type", "month");
    expect(screen.getByLabelText("月份")).toHaveAttribute("max", "2026-07");
    expect(screen.getByRole("button", { name: "后一月" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "前一月" }));
    expect(onChange).toHaveBeenCalledWith("month", { start: "2026-06-01", end: "2026-06-30" });
    fireEvent.click(screen.getByRole("button", { name: "导出当前范围" }));
    expect(onExport).toHaveBeenCalledOnce();
  });

  it("directly selects a month and rejects future months", () => {
    const onChange = vi.fn();
    render(<RecordFilters {...props} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("月份"), { target: { value: "2026-01" } });
    expect(onChange).toHaveBeenCalledWith("month", { start: "2026-01-01", end: "2026-01-31" });
    onChange.mockClear();
    fireEvent.change(screen.getByLabelText("月份"), { target: { value: "2026-08" } });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("未来月份不可选择");
  });

  it("opens a month-based custom range and resolves past and current end boundaries", () => {
    const onChange = vi.fn();
    render(<RecordFilters {...props} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "自定义范围" }));
    expect(screen.getByTestId("record-filter-months")).toHaveClass("grid", "grid-cols-2");
    expect(screen.getByLabelText("开始月份")).toHaveAttribute("type", "month");
    expect(screen.getByLabelText("结束月份")).toHaveAttribute("type", "month");
    expect(onChange).toHaveBeenLastCalledWith("custom", { start: "2026-07-01", end: "2026-07-17" });

    fireEvent.change(screen.getByLabelText("开始月份"), { target: { value: "2026-05" } });
    fireEvent.change(screen.getByLabelText("结束月份"), { target: { value: "2026-06" } });
    expect(onChange).toHaveBeenLastCalledWith("custom", { start: "2026-05-01", end: "2026-06-30" });
  });

  it("keeps invalid custom drafts visible without emitting a query range", () => {
    const onChange = vi.fn();
    render(<RecordFilters {...props} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "自定义范围" }));
    onChange.mockClear();

    fireEvent.change(screen.getByLabelText("开始月份"), { target: { value: "2026-08" } });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("未来月份不可选择");
    expect(screen.getByRole("button", { name: "导出当前范围" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("开始月份"), { target: { value: "2026-07" } });
    onChange.mockClear();
    fireEvent.change(screen.getByLabelText("结束月份"), { target: { value: "2026-06" } });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("结束月份不能早于开始月份");
  });

  it("preserves an invalid custom draft across value-equivalent range props", () => {
    const view = render(<RecordFilters {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "自定义范围" }));
    fireEvent.change(screen.getByLabelText("开始月份"), { target: { value: "2026-08" } });

    view.rerender(<RecordFilters {...props} range={{ start: "2026-07-01", end: "2026-07-31" }} />);
    expect(screen.getByLabelText("开始月份")).toHaveValue("2026-08");
    expect(screen.getByLabelText("结束月份")).toHaveValue("2026-07");
  });

  it("clears an invalid draft when an external range changes", () => {
    const view = render(<RecordFilters {...props} />);
    fireEvent.change(screen.getByLabelText("月份"), { target: { value: "2026-08" } });
    expect(screen.getByRole("alert")).toHaveTextContent("未来月份不可选择");

    view.rerender(<RecordFilters {...props} range={{ start: "2026-06-01", end: "2026-06-30" }} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("月份")).toHaveValue("2026-06");
  });

  it("closes custom controls after an external mode change and exposes export errors", () => {
    const view = render(<RecordFilters {...props} mode="custom" exportError="导出失败，请重试" />);
    expect(screen.getByTestId("record-filter-months")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("导出失败，请重试");

    view.rerender(<RecordFilters {...props} mode="month" />);
    expect(screen.queryByTestId("record-filter-months")).not.toBeInTheDocument();
  });
});
