import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RecordSnapshot } from "@/api/types";
import { MobileRecordList } from "@/components/MobileRecordList";

const record: RecordSnapshot = {
  id: 7, store_id: 3, date: "2026-07-14", daily_revenue: 100, wash_count: 4, is_open: "休息",
  income_mode: "legacy_total", weather: "晴", weather_auto: null,
  weather_code: null, temperature_max: null, temperature_min: null, precipitation: null, activity: "活动",
  weather_edited: false, scanned: false, created_by: 1, updated_by: 1, created_at: "2026-07-14T00:00:00Z",
  updated_at: "2026-07-14T00:00:00Z", created_by_name: "小王", updated_by_name: "小李", items: [],
};

describe("MobileRecordList", () => {
  it("uses a compact accessible three-column trigger without extra record fields", () => {
    const onSelect = vi.fn();
    render(<MobileRecordList records={[record]} selectedDate={record.date} onSelect={onSelect} />);

    const row = screen.getByRole("button", { name: /2026年7月14日，休息，€100/ });
    expect(row).toHaveClass("py-2");
    expect(row).not.toHaveClass("py-3");
    expect(row).toHaveAttribute("aria-pressed", "true");
    row.click();
    expect(onSelect).toHaveBeenCalledWith(record, row);
    expect(screen.queryByText("晴")).not.toBeInTheDocument();
    expect(screen.queryByText("活动")).not.toBeInTheDocument();
    expect(screen.queryByText("4")).not.toBeInTheDocument();
    expect(screen.queryByText("记账事件")).not.toBeInTheDocument();
    expect(screen.queryByText(/小王|小李/)).not.toBeInTheDocument();
  });
});
