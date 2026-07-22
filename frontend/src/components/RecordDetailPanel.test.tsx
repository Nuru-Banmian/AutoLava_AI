import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { RecordSnapshot } from "@/api/types";
import { RecordDetailPanel } from "@/components/RecordDetailPanel";

const record: RecordSnapshot = {
  id: 4, store_id: 1, date: "2026-07-14", daily_revenue: 100, income_mode: "composed",
  wash_count: 8, is_open: "营业", weather: "晴", weather_auto: "晴", weather_code: 1, temperature_max: "20.0", temperature_min: "10.0", precipitation: "0.0",
  activity: null, weather_edited: false, scanned: false, created_by: 1, updated_by: 1, created_at: "", updated_at: "", created_by_name: "admin", updated_by_name: "admin",
  items: [{ id: 1, category_id: 1, category_name: "现金", include_in_total: true, sort_order: 1, amount: 100, created_at: "", updated_at: "" }],
};

function renderPanel(value: RecordSnapshot, canDelete = false, onDelete = vi.fn()) {
  return render(<MemoryRouter><RecordDetailPanel record={value} canEdit canDelete={canDelete} onDelete={onDelete} /></MemoryRouter>);
}

describe("RecordDetailPanel", () => {
  it("renders an unrecorded date with the same edit action position", () => {
    render(
      <MemoryRouter>
        <RecordDetailPanel record={{ id: null, date: "2026-07-15" }} canEdit canDelete onDelete={vi.fn()} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "2026年7月15日" })).toBeInTheDocument();
    expect(screen.getByText("未录入", { exact: true })).toBeInTheDocument();
    expect(screen.getAllByText("—", { exact: true })).toHaveLength(3);
    expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-15");
    expect(screen.queryByRole("button", { name: "删除这天记录" })).not.toBeInTheDocument();
  });

  it("renders rest records without fabricating an open status", () => {
    renderPanel({ ...record, is_open: "休息", wash_count: 0, activity: "会员日" });

    expect(screen.getByRole("heading", { name: "2026年7月14日" })).toHaveClass("text-xl");
    const statusText = screen.getByText("休息", { exact: true });
    expect(statusText).toHaveClass("text-lg");
    expect(statusText.parentElement).toHaveClass("rounded-xl", "bg-muted/50", "p-3");
    const statusValue = statusText.closest("p");
    expect(statusValue).not.toBeNull();
    expect(statusValue?.querySelector('[aria-hidden="true"]')).toBeNull();
    expect(screen.queryByText("营业", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("洗车数量 0")).toBeInTheDocument();
    expect(screen.getByText(/会员日/)).toBeInTheDocument();
    expect(screen.queryByText("计入总营业额")).not.toBeInTheDocument();
    expect(screen.queryByText("独立记录")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "收入明细" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-14");
    expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveClass("h-10", "text-base");
    expect(screen.queryByRole("button", { name: "删除这天记录" })).not.toBeInTheDocument();
  });

  it("shows a destructive delete action for a saved record when allowed", () => {
    const onDelete = vi.fn();
    renderPanel(record, true, onDelete);

    const action = screen.getByRole("button", { name: "删除这天记录" });
    expect(action.className).toContain("destructive");
    action.click();
    expect(onDelete).toHaveBeenCalledOnce();
  });

  it.each(["营业", "天气停业"] as const)("shows the actual %s status", (is_open) => {
    renderPanel({ ...record, is_open });

    expect(screen.getByText(is_open, { exact: true })).toBeInTheDocument();
  });

  it("explains a legacy total-only record", () => {
    renderPanel({ ...record, income_mode: "legacy_total", items: [] });

    expect(screen.getByText("历史记录仅保存营业额总计")).toBeInTheDocument();
    expect(screen.queryByText("现金")).not.toBeInTheDocument();
  });

  it("lays out any number of income categories without showing total-inclusion metadata", () => {
    const items = Array.from({ length: 7 }, (_, index) => ({
      ...record.items[0],
      id: index + 1,
      category_id: index + 1,
      category_name: index === 0 ? "名称很长的多渠道合作伙伴收入分类" : `分类${index + 1}`,
      include_in_total: index % 2 === 0,
      amount: (index + 1) * 10,
    }));
    renderPanel({ ...record, items });

    const details = screen.getByRole("heading", { name: "收入明细" }).parentElement?.querySelector("dl");
    expect(details).not.toBeNull();
    expect(details).toHaveTextContent("名称很长的多渠道合作伙伴收入分类");
    expect(details).toHaveClass("grid-cols-[repeat(auto-fit,minmax(min(100%,9rem),1fr))]");
    expect(screen.getAllByRole("term")).toHaveLength(7);
    expect(screen.queryByText("计入总营业额")).not.toBeInTheDocument();
    expect(screen.queryByText("独立记录")).not.toBeInTheDocument();
  });
});
