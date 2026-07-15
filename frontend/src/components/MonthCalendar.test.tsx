import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LedgerDatePicker } from "@/components/LedgerDatePicker";
import { MonthCalendar } from "@/components/MonthCalendar";

afterEach(() => vi.unstubAllGlobals());

describe("MonthCalendar", () => {
  it("marks recorded dates and blocks future dates", () => {
    const onSelect = vi.fn();

    render(
      <MonthCalendar
        month="2026-07"
        selected="2026-07-15"
        today="2026-07-15"
        recordedDates={new Set(["2026-07-14"])}
        onSelect={onSelect}
      />,
    );

    const recorded = screen.getByRole("button", { name: "2026年7月14日，已有记录" });
    expect(recorded).toBeEnabled();
    expect(recorded).toHaveAttribute("data-recorded", "true");
    expect(screen.getByRole("button", { name: "2026年7月15日" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "2026年7月16日" })).toBeDisabled();

    fireEvent.click(recorded);
    expect(onSelect).toHaveBeenCalledWith("2026-07-14");
  });

  it("starts weeks on Monday and marks dates across month boundaries", () => {
    render(
      <MonthCalendar
        month="2026-07"
        selected="2026-07-15"
        today="2026-08-31"
        recordedDates={new Set()}
        onSelect={() => undefined}
      />,
    );

    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual(["一", "二", "三", "四", "五", "六", "日"]);
    expect(screen.getByRole("button", { name: "2026年6月29日" })).toHaveAttribute("data-outside", "true");
    expect(screen.getByRole("button", { name: "2026年8月2日" })).toHaveAttribute("data-outside", "true");
    expect(screen.getByRole("button", { name: "2026年7月1日" })).not.toHaveAttribute("data-outside");
  });
});

describe("LedgerDatePicker", () => {
  it("opens from the visible date, offers shortcuts, and navigates month boundaries", () => {
    const onChange = vi.fn();
    render(
      <LedgerDatePicker
        value="2026-07-14"
        today="2026-07-15"
        recordedDates={new Set(["2026-07-14"])}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "选择台账日期：2026年7月14日" }));
    expect(screen.getByRole("dialog", { name: "选择台账日期" })).toBeInTheDocument();
    expect(screen.getByText("编辑已有记录")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "上个月" }));
    expect(screen.getByText("2026年6月")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下个月" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "下个月" }));

    fireEvent.click(screen.getByRole("button", { name: "昨天" }));
    expect(onChange).toHaveBeenCalledWith("2026-07-14");
  });

  it("uses a bottom sheet on narrow screens", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: false,
      media: "(min-width: 640px)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));

    render(<LedgerDatePicker value="2026-07-15" today="2026-07-15" recordedDates={new Set()} onChange={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "选择台账日期：2026年7月15日" }));

    expect(screen.getByRole("dialog", { name: "选择台账日期" })).toHaveClass("bottom-0", "rounded-t-2xl");
  });
});
