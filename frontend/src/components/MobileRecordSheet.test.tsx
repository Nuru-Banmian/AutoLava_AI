import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { RecordSnapshot } from "@/api/types";
import { MobileRecordSheet } from "@/components/MobileRecordSheet";

const record: RecordSnapshot = {
  id: 4, store_id: 1, date: "2026-07-14", daily_revenue: 100, income_mode: "composed",
  wash_count: 8, is_open: "营业", weather: "晴", weather_auto: "晴", weather_code: 1, temperature_max: "20.0", temperature_min: "10.0", precipitation: "0.0",
  activity: null, weather_edited: false, scanned: false, created_by: 1, updated_by: 1, created_at: "", updated_at: "",
  items: [],
};

function ControlledSheet() {
  const [open, setOpen] = useState(false);
  const [trigger, setTrigger] = useState<HTMLButtonElement | null>(null);
  return <MemoryRouter>
    <button ref={setTrigger} type="button" onClick={() => setOpen(true)}>打开记录</button>
    <MobileRecordSheet open={open} record={record} canEdit canManage={false} onManage={vi.fn()} returnFocusTo={trigger} onOpenChange={setOpen} />
  </MemoryRouter>;
}

describe("MobileRecordSheet", () => {
  it("restores focus to the opening record button after close", async () => {
    render(<ControlledSheet />);
    const trigger = screen.getByRole("button", { name: "打开记录" });

    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "2026-07-14 营业记录详情" });
    expect(dialog.className).toContain("safe-area-inset-bottom");
    expect(screen.getByText("营业", { exact: true })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
