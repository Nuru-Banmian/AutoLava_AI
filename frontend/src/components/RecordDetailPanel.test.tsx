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

function renderPanel(value: RecordSnapshot, canDelete = false, onDelete = vi.fn(), washCountEnabled = true) {
  return render(
    <MemoryRouter>
      <RecordDetailPanel
        record={value}
        canEdit
        canDelete={canDelete}
        washCountEnabled={washCountEnabled}
        timeZone="Europe/Rome"
        onDelete={onDelete}
      />
    </MemoryRouter>,
  );
}

describe("RecordDetailPanel", () => {
  it("renders an unrecorded date with the same edit action position", () => {
    render(
      <MemoryRouter>
        <RecordDetailPanel
          record={{ id: null, date: "2026-07-15" }}
          canEdit
          canDelete
          washCountEnabled
          timeZone="Europe/Rome"
          onDelete={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "2026年7月15日" })).toBeInTheDocument();
    expect(screen.getByText("未录入", { exact: true })).toBeInTheDocument();
    expect(screen.getAllByText("—", { exact: true })).toHaveLength(2);
    expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-15");
    expect(screen.queryByRole("button", { name: "删除记录" })).not.toBeInTheDocument();
  });

  it("keeps the date, textual status, revenue, weather, wash count, and event easy to scan", () => {
    renderPanel({ ...record, is_open: "提前休息", activity: "会员日照常营业" });

    const heading = screen.getByRole("heading", { name: "2026年7月14日" });
    expect(heading.parentElement).toHaveClass("flex-row", "flex-wrap");
    expect(heading.parentElement).toHaveTextContent("2026年7月14日提前休息");
    expect(screen.getByText("提前休息", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("营业状态", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("营业额", { exact: true }).parentElement).toHaveTextContent("营业额€100");
    expect(screen.getByText("晴", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("洗车 8 辆", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("洗车数量", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("事件：", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("会员日照常营业", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("活动：", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText("计入总营业额")).not.toBeInTheDocument();
    expect(screen.queryByText("独立记录")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "收入明细" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-14");
    expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveClass("h-10", "text-base");
    expect(screen.queryByRole("button", { name: "删除记录" })).not.toBeInTheDocument();
  });

  it("shows the automatically recorded bookkeeping events in the saved-record detail card", () => {
    renderPanel({
      ...record,
      created_by: 1,
      created_by_name: "小王",
      created_at: "2026-07-14T08:30:00",
      updated_by: 2,
      updated_by_name: "小李",
      updated_at: "2026-07-14T10:45:00",
      bookkeeping_events: [
        { id: 1, action: "created", actor_id: 1, actor_name: "小王", occurred_at: "2026-07-14T06:30:00Z", timestamp_status: "utc" },
        { id: 2, action: "updated", actor_id: 2, actor_name: "小李", occurred_at: "2026-07-14T08:45:00Z", timestamp_status: "utc" },
        { id: 3, action: "updated", actor_id: 1, actor_name: "小王", occurred_at: "2026-07-14T09:00:00Z", timestamp_status: "utc" },
      ],
    });

    const events = screen.getByRole("region", { name: "记账事件" });
    expect(events).toHaveTextContent("小王创建记录");
    expect(events).toHaveTextContent("2026年7月14日 08:30");
    expect(events).toHaveTextContent("小李修改记录");
    expect(events).toHaveTextContent("2026年7月14日 10:45");
    expect(events).toHaveTextContent("小王修改记录");
    expect(events).toHaveTextContent("2026年7月14日 11:00");
    expect(events.querySelectorAll("li")).toHaveLength(3);
  });

  it("shows a destructive delete action for a saved record when allowed", () => {
    const onDelete = vi.fn();
    renderPanel(record, true, onDelete);

    const action = screen.getByRole("button", { name: "删除记录" });
    expect(action.className).toContain("destructive");
    action.click();
    expect(onDelete).toHaveBeenCalledOnce();
  });

  it.each(["营业", "休息", "提前休息"] as const)("shows the actual %s status beside the date heading", (is_open) => {
    renderPanel({ ...record, is_open });

    const heading = screen.getByRole("heading", { name: "2026年7月14日" });
    expect(heading.parentElement).toHaveTextContent(`2026年7月14日${is_open}`);
  });

  it.each([
    { label: "zero", washCount: 0, enabled: true },
    { label: "empty", washCount: null, enabled: true },
    { label: "disabled setting", washCount: 8, enabled: false },
  ])("does not reserve detail space for wash count when $label", ({ washCount, enabled }) => {
    renderPanel({ ...record, wash_count: washCount }, false, vi.fn(), enabled);

    expect(screen.queryByText(/洗车 \d+ 辆/)).not.toBeInTheDocument();
    expect(screen.queryByText("洗车数量", { exact: true })).not.toBeInTheDocument();
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
