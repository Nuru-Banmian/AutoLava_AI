import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NativeDateInput } from "@/components/NativeDateInput";

describe("NativeDateInput", () => {
  it("renders the shared native date contract and a touch-sized calendar trigger", () => {
    render(<NativeDateInput aria-label="开始日期" value="2026-07-01" max="2026-07-17" onChange={vi.fn()} />);

    const input = screen.getByLabelText("开始日期");
    const trigger = screen.getByRole("button", { name: "打开开始日期日历" });
    expect(input).toHaveAttribute("type", "date");
    expect(input).toHaveAttribute("max", "2026-07-17");
    expect(input).toHaveClass("min-h-11", "pr-11");
    expect(trigger).toHaveClass("size-11");
  });

  it("opens the input's native picker from its calendar trigger", async () => {
    const user = userEvent.setup();
    render(<NativeDateInput aria-label="开始日期" value="2026-07-01" onChange={vi.fn()} />);

    const input = screen.getByLabelText("开始日期") as HTMLInputElement & { showPicker?: () => void };
    const showPicker = vi.fn();
    Object.defineProperty(input, "showPicker", { configurable: true, value: showPicker });

    await user.click(screen.getByRole("button", { name: "打开开始日期日历" }));

    expect(showPicker).toHaveBeenCalledOnce();
  });

  it("focuses the input when the browser does not support showPicker", async () => {
    const user = userEvent.setup();
    render(<NativeDateInput aria-label="分析开始日期" value="2026-07-01" onChange={vi.fn()} />);

    const input = screen.getByLabelText("分析开始日期") as HTMLInputElement & { showPicker?: () => void };
    Object.defineProperty(input, "showPicker", { configurable: true, value: undefined });

    await user.click(screen.getByRole("button", { name: "打开分析开始日期日历" }));

    expect(input).toHaveFocus();
  });
});
