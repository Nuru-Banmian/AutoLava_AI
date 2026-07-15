import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { IncomeConfigResponse, RecordSnapshot } from "@/api/types";
import { LedgerForm } from "@/components/LedgerForm";

describe("LedgerForm", () => {
  function renderLedgerForm(config: IncomeConfigResponse) {
    return render(<LedgerForm categories={[]} config={config} onSave={vi.fn()} />);
  }

  it("uses direct total when configuration is disabled", () => {
    renderLedgerForm({ store_id: 2, enabled: false, version_id: 4, version: 4, formula: "", created_at: null, items: [] });

    expect(screen.getByLabelText("当日营业额")).toBeEnabled();
    expect(screen.queryByRole("group", { name: "收入项目" })).not.toBeInTheDocument();
  });

  it("uses only active configured items in composed mode", () => {
    const onSave = vi.fn();
    render(
      <LedgerForm
        config={{
          store_id: 2,
          enabled: true,
          version_id: 4,
          version: 4,
          formula: "现金",
          created_at: "2026-07-15T08:00:00",
          items: [
            { id: 10, category_id: 5, name: "现金", include_in_total: true, is_active: true, sort_order: 0 },
            { id: 11, category_id: 6, name: "停用项", include_in_total: true, is_active: false, sort_order: 1 },
          ],
        }}
        categories={[
          { id: 5, name: "现金", include_in_total: true, is_active: true, sort_order: 0 },
          { id: 6, name: "停用项", include_in_total: true, is_active: true, sort_order: 1 },
          { id: 7, name: "目录外项目", include_in_total: true, is_active: true, sort_order: 2 },
        ]}
        onSave={onSave}
      />,
    );

    expect(screen.getByRole("group", { name: "收入项目" })).toBeInTheDocument();
    expect(screen.getByLabelText("现金")).toBeEnabled();
    expect(screen.queryByLabelText("停用项")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("目录外项目")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("当日营业额")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "12,3" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      daily_revenue: null,
      config_version_id: 4,
      items: [{ category_id: 5, amount: "12.30" }],
    }));
  });

  it("preserves a total-only record when the current configuration is enabled", () => {
    const onSave = vi.fn();
    const record = {
      id: 12,
      store_id: 2,
      date: "2026-07-14",
      daily_revenue: "98.76",
      income_mode: "legacy_total",
      income_config_version_id: 4,
      row_version: 5,
      items: [],
      is_open: "营业",
      wash_count: null,
      weather: null,
      weather_auto: null,
      weather_code: null,
      temperature_max: null,
      temperature_min: null,
      precipitation: null,
      activity: null,
      weather_edited: false,
      scanned: false,
      created_by: 1,
      updated_by: 1,
      created_at: "2026-07-14T08:00:00",
      updated_at: "2026-07-14T08:00:00",
    } satisfies RecordSnapshot & { income_mode: "legacy_total" };

    render(
      <LedgerForm
        config={{ store_id: 2, enabled: true, version_id: 4, version: 4, formula: "现金", created_at: "2026-07-15T08:00:00", items: [{ id: 10, category_id: 5, name: "现金", include_in_total: true, is_active: true, sort_order: 0 }] }}
        categories={[{ id: 5, name: "现金", include_in_total: true, is_active: true, sort_order: 0 }]}
        record={record}
        onSave={onSave}
      />,
    );

    expect(screen.getByLabelText("当日营业额")).toHaveValue("98.76");
    expect(screen.queryByRole("group", { name: "收入项目" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      daily_revenue: "98.76",
      config_version_id: null,
      expected_version: 5,
      items: [],
    }));
  });

  it("binds an edited composed record to its config and row versions", () => {
    const onSave = vi.fn();
    const record: RecordSnapshot & {
      income_config_version_id: number;
      row_version: number;
    } = {
      id: 11,
      store_id: 2,
      date: "2026-07-15",
      daily_revenue: "12.00",
      income_mode: "composed",
      wash_count: null,
      is_open: "营业",
      weather: null,
      weather_auto: null,
      weather_code: null,
      temperature_max: null,
      temperature_min: null,
      precipitation: null,
      activity: null,
      weather_edited: false,
      scanned: false,
      created_by: 1,
      updated_by: 1,
      created_at: "2026-07-15T08:00:00",
      updated_at: "2026-07-15T08:00:00",
      income_config_version_id: 7,
      row_version: 3,
      items: [
        {
          id: 21,
          category_id: 5,
          category_name: "现金",
          include_in_total: true,
          sort_order: 0,
          amount: "12.00",
          created_at: "2026-07-15T08:00:00",
          updated_at: "2026-07-15T08:00:00",
        },
      ],
    };

    render(
      <LedgerForm
        config={{
          store_id: 2,
          enabled: true,
          version_id: 7,
          version: 7,
          formula: "现金 + 新增项",
          created_at: "2026-07-15T08:00:00",
          items: [
            { id: 31, category_id: 5, name: "现金", include_in_total: true, is_active: true, sort_order: 0 },
            { id: 32, category_id: 6, name: "新增项", include_in_total: true, is_active: true, sort_order: 1 },
          ],
        }}
        categories={[
          {
            id: 5,
            name: "现金",
            include_in_total: true,
            is_active: true,
            sort_order: 0,
          },
          {
            id: 6,
            name: "新增项",
            include_in_total: true,
            is_active: true,
            sort_order: 1,
          },
        ]}
        record={record}
        onSave={onSave}
      />,
    );

    expect(screen.queryByLabelText("新增项")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        config_version_id: 7,
        expected_version: 3,
        daily_revenue: null,
        items: [{ category_id: 5, amount: "12.00" }],
      }),
    );
  });
});
