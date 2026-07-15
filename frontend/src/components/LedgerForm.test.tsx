import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RecordSnapshot } from "@/api/types";
import { LedgerForm } from "@/components/LedgerForm";

describe("LedgerForm", () => {
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
          amount: "12.00",
          created_at: "2026-07-15T08:00:00",
          updated_at: "2026-07-15T08:00:00",
        },
      ],
    };

    render(
      <LedgerForm
        categories={[
          {
            id: 5,
            name: "现金",
            include_in_total: true,
            is_active: true,
            sort_order: 0,
          },
        ]}
        record={record}
        onSave={onSave}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        config_version_id: 7,
        expected_version: 3,
        daily_revenue: null,
      }),
    );
  });
});
