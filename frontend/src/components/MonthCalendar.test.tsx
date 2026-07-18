import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("owns headers and days through row elements with one roving tab stop", () => {
    render(<MonthCalendar month="2026-07" selected="2026-07-14" today="2026-07-15" recordedDates={new Set()} onSelect={() => undefined} />);

    const grid = screen.getByRole("grid", { name: "2026年7月日历" });
    expect(grid.querySelectorAll(":scope > [role=row]")).toHaveLength(6);
    expect(screen.getAllByRole("button").filter((button) => button.tabIndex === 0)).toEqual([
      screen.getByRole("button", { name: "2026年7月14日" }),
    ]);
    expect(screen.getByRole("button", { name: "2026年7月16日" })).toHaveAttribute("tabindex", "-1");

    const julyThirteenth = screen.getByRole("button", { name: "2026年7月13日" });
    fireEvent.focus(julyThirteenth);
    expect(screen.getAllByRole("button").filter((button) => button.tabIndex === 0)).toEqual([julyThirteenth]);
  });

  it("moves focus by day and week without entering future dates", async () => {
    const user = userEvent.setup();
    render(<MonthCalendar month="2026-07" selected="2026-07-15" today="2026-07-15" recordedDates={new Set()} onSelect={() => undefined} />);
    const selected = screen.getByRole("button", { name: "2026年7月15日" });
    selected.focus();

    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("button", { name: "2026年7月14日" })).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("button", { name: "2026年7月7日" })).toHaveFocus();
    await user.keyboard("{ArrowDown}{ArrowRight}");
    expect(selected).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(selected).toHaveFocus();
  });

  it("moves to week boundaries, crosses visible month edges, and selects from the keyboard", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<MonthCalendar month="2026-07" selected="2026-07-01" today="2026-07-15" recordedDates={new Set()} onSelect={onSelect} />);
    const julyFirst = screen.getByRole("button", { name: "2026年7月1日" });
    julyFirst.focus();

    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("button", { name: "2026年6月30日" })).toHaveFocus();
    await user.keyboard("{Home}");
    expect(screen.getByRole("button", { name: "2026年6月29日" })).toHaveFocus();
    await user.keyboard("{End}");
    const julyFifth = screen.getByRole("button", { name: "2026年7月5日" });
    expect(julyFifth).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith("2026-07-05");
    await user.keyboard(" ");
    expect(onSelect).toHaveBeenCalledTimes(2);
  });
});

describe("LedgerDatePicker", () => {
  it("reports the visible calendar month while open", () => {
    const onMonthChange = vi.fn();
    render(
      <LedgerDatePicker
        value="2026-07-14"
        today="2026-07-15"
        recordedDates={new Set()}
        onChange={() => undefined}
        onMonthChange={onMonthChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "选择台账日期：2026年7月14日" }));
    expect(onMonthChange).toHaveBeenLastCalledWith("2026-07");
    fireEvent.click(screen.getByRole("button", { name: "上个月" }));
    expect(onMonthChange).toHaveBeenLastCalledWith("2026-06");
  });

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

  it("resets to the selected date month each time it reopens", () => {
    const onMonthChange = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <LedgerDatePicker
        value="2026-07-14"
        today="2026-07-15"
        recordedDates={new Set()}
        onChange={() => undefined}
        onMonthChange={onMonthChange}
        onOpenChange={onOpenChange}
      />,
    );

    const trigger = screen.getByRole("button", { name: "选择台账日期：2026年7月14日" });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "上个月" }));
    expect(screen.getByText("2026年6月")).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole("dialog", { name: "选择台账日期" }), { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "选择台账日期" })).not.toBeInTheDocument();

    fireEvent.click(trigger);
    expect(screen.getByText("2026年7月")).toBeInTheDocument();
    expect(onMonthChange).toHaveBeenLastCalledWith("2026-07");
    expect(onOpenChange).toHaveBeenLastCalledWith(true);
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
    const trigger = screen.getByRole("button", { name: "选择台账日期：2026年7月15日" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);

    const sheet = screen.getByRole("dialog", { name: "选择台账日期" });
    expect(sheet).toHaveClass("bottom-0", "rounded-t-2xl");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-controls", sheet.id);
  });

  it("exposes dialog trigger state and restores focus after closing", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<LedgerDatePicker value="2026-07-15" today="2026-07-15" recordedDates={new Set()} onChange={onChange} />);
    const trigger = screen.getByRole("button", { name: "选择台账日期：2026年7月15日" });

    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "选择台账日期" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-controls", dialog.id);

    await user.keyboard("{Escape}");
    expect(dialog).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "昨天" }));
    expect(onChange).toHaveBeenCalledWith("2026-07-14");
    expect(trigger).toHaveFocus();
  });
});
