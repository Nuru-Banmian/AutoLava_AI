import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NativeDateInput } from "@/components/NativeDateInput";

describe("NativeDateInput", () => {
  it("renders the shared native date contract", () => {
    render(<NativeDateInput aria-label="开始日期" value="2026-07-01" max="2026-07-17" onChange={vi.fn()} />);

    const input = screen.getByLabelText("开始日期");
    expect(input).toHaveAttribute("type", "date");
    expect(input).toHaveAttribute("max", "2026-07-17");
    expect(input).toHaveClass("min-h-11", "pr-11");
  });
});
