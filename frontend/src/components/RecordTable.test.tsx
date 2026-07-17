import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RecordSnapshot } from "@/api/types";
import { RecordTable } from "@/components/RecordTable";

const record: RecordSnapshot = {
  id: 7, store_id: 3, date: "2026-07-14", daily_revenue: "100.00", wash_count: 4, is_open: "休息",
  income_mode: "legacy_total", income_config_version_id: null, row_version: 1, weather: "晴", weather_auto: null,
  weather_code: null, temperature_max: null, temperature_min: null, precipitation: null, activity: "活动",
  weather_edited: false, scanned: false, created_by: 1, updated_by: 1, created_at: "2026-07-14T00:00:00Z",
  updated_at: "2026-07-14T00:00:00Z", items: [],
};

describe("RecordTable", () => {
  it("uses a semantic four-column table and activates the selected row by keyboard", () => {
    const onSelect = vi.fn();
    const onRetry = vi.fn();
    render(<RecordTable records={[record]} selectedId={record.id} loading={false} error={null} onSelect={onSelect} onRetry={onRetry} />);

    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["日期", "状态", "总营业额", "天气"]);
    expect(screen.queryByRole("columnheader", { name: /洗车|活动|收入/ })).not.toBeInTheDocument();
    const row = screen.getByRole("row", { name: /2026年7月14日 休息/ });
    expect(row).toHaveAttribute("aria-selected", "true");
    expect(row).toHaveTextContent("休息");
    fireEvent.keyDown(row, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith(record);
  });

  it("uses Space to activate records and renders loading, errors, and an empty state", () => {
    const onSelect = vi.fn();
    const onRetry = vi.fn();
    const { rerender } = render(<RecordTable records={[record]} selectedId={null} loading={false} error={null} onSelect={onSelect} onRetry={onRetry} />);

    fireEvent.keyDown(screen.getByRole("row", { name: /2026年7月14日 休息/ }), { key: " " });
    expect(onSelect).toHaveBeenCalledWith(record);

    rerender(<RecordTable records={[]} selectedId={null} loading error={null} onSelect={onSelect} onRetry={onRetry} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    rerender(<RecordTable records={[]} selectedId={null} loading={false} error={new Error("加载失败")} onSelect={onSelect} onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("加载失败");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalledOnce();
    rerender(<RecordTable records={[]} selectedId={null} loading={false} error={null} onSelect={onSelect} onRetry={onRetry} />);
    expect(screen.getByText("暂无记录")).toBeInTheDocument();
  });
});
