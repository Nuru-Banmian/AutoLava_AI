import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { IncomeConfigResponse, LedgerBody, RecordSnapshot } from "@/api/types";
import { LedgerForm } from "@/components/LedgerForm";

const directConfig = {
  store_id: 2,
  enabled: false,
  formula: "",
  items: [],
} as IncomeConfigResponse;

const composedConfig = {
  store_id: 2,
  enabled: true,
  formula: "营业额 = 现金",
  items: [
    { id: 5, store_id: 2, name: "现金", include_in_total: true, is_active: true, sort_order: 0, archived_at: null },
    { id: 6, store_id: 2, name: "不计入", include_in_total: false, is_active: true, sort_order: 1, archived_at: null },
  ],
} as IncomeConfigResponse;

function savedRecord(overrides: Partial<RecordSnapshot> = {}): RecordSnapshot {
  return {
    id: 11,
    store_id: 2,
    date: "2026-07-15",
    daily_revenue: 12,
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
    items: [{
      id: 21,
      category_id: 5,
      category_name: "历史现金",
      include_in_total: true,
      sort_order: 0,
      amount: 12,
      created_at: "2026-07-15T08:00:00",
      updated_at: "2026-07-15T08:00:00",
    }],
    ...overrides,
  };
}

describe("LedgerForm", () => {
  it("uses direct total when configuration is disabled", () => {
    render(<LedgerForm categories={[]} config={directConfig} onSave={vi.fn()} />);

    const input = screen.getByLabelText("当日营业额");
    expect(input).toHaveAttribute("type", "text");
    expect(input).toHaveAttribute("inputmode", "numeric");
    expect(screen.queryByRole("group", { name: "收入项目" })).not.toBeInTheDocument();
  });

  it("starts new business and weather-closure amounts empty in both ledger modes", () => {
    const direct = render(<LedgerForm categories={[]} config={directConfig} onSave={vi.fn()} />);
    expect(screen.getByLabelText("当日营业额")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("状态"), { target: { value: "天气停业" } });
    expect(screen.getByLabelText("当日营业额")).toHaveValue("");
    direct.unmount();

    render(<LedgerForm categories={[]} config={composedConfig} onSave={vi.fn()} />);
    expect(screen.getByLabelText("现金")).toHaveValue("");
    expect(screen.getByLabelText("不计入")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("状态"), { target: { value: "天气停业" } });
    expect(screen.getByLabelText("现金")).toHaveValue("");
    expect(screen.getByLabelText("不计入")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("状态"), { target: { value: "休息" } });
    fireEvent.change(screen.getByLabelText("状态"), { target: { value: "营业" } });
    expect(screen.getByLabelText("现金")).toHaveValue("");
    expect(screen.getByLabelText("不计入")).toHaveValue("");
  });

  it("accepts only whole non-negative money input", () => {
    const onSave = vi.fn();
    render(<LedgerForm categories={[]} config={directConfig} onSave={onSave} />);

    for (const value of ["", "-1", "1.2", "1e2", " 1", "1 "]) {
      fireEvent.change(screen.getByLabelText("当日营业额"), { target: { value } });
      fireEvent.click(screen.getByRole("button", { name: "保存" }));
      expect(screen.getByRole("alert")).toHaveTextContent("金额必须是大于等于 0 的整数");
    }
    expect(onSave).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("当日营业额"), { target: { value: "123" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ daily_revenue: 123, items: [] }));
  });

  it("sums only included categories and saves no version fields", () => {
    const onSave = vi.fn<(body: LedgerBody) => void>();
    render(<LedgerForm categories={[]} config={composedConfig} onSave={onSave} />);

    fireEvent.change(screen.getByLabelText("现金"), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText("不计入"), { target: { value: "99" } });
    expect(screen.getByText("合计 €12")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    const body = onSave.mock.calls[0][0] as LedgerBody & Record<string, unknown>;
    expect(body).toEqual(expect.objectContaining({
      daily_revenue: null,
      items: [{ category_id: 5, amount: 12 }, { category_id: 6, amount: 99 }],
    }));
    expect(body).not.toHaveProperty("config_version_id");
    expect(body).not.toHaveProperty("expected_version");
  });

  it("uses the loaded record's item snapshots and snapshot order", () => {
    const record = savedRecord({
      daily_revenue: 15,
      items: [
        { id: 22, category_id: 6, category_name: "历史第二项", include_in_total: false, sort_order: 2, amount: 90, created_at: "", updated_at: "" },
        { id: 21, category_id: 5, category_name: "历史第一项", include_in_total: true, sort_order: 1, amount: 15, created_at: "", updated_at: "" },
      ],
    });
    render(<LedgerForm categories={[]} config={{
      ...composedConfig,
      items: [{ ...composedConfig.items[0], name: "当前已改名", include_in_total: false, sort_order: 3 }],
    }} record={record} onSave={vi.fn()} />);

    const first = screen.getByLabelText("历史第一项");
    const second = screen.getByLabelText("历史第二项");
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByLabelText("当前已改名")).not.toBeInTheDocument();
    expect(screen.getByText("合计 €15")).toBeInTheDocument();
  });

  it("preserves a direct-mode saved record even when current configuration is composed", () => {
    const onSave = vi.fn();
    render(<LedgerForm categories={[]} config={composedConfig} record={savedRecord({
      daily_revenue: 98,
      income_mode: "legacy_total",
      items: [],
    })} onSave={onSave} />);

    expect(screen.getByLabelText("当日营业额")).toHaveValue("98");
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ daily_revenue: 98, items: [] }));
  });

  it("absorbs late automatic weather while the form is clean", () => {
    const view = render(<LedgerForm categories={[]} config={directConfig} onSave={vi.fn()} />);
    view.rerender(<LedgerForm categories={[]} config={directConfig} weather={{ weather: "晴", weather_code: 1, temperature_max: 20, temperature_min: 10, precipitation: 0 }} onSave={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "天气" })).toHaveTextContent("晴");
  });

  it("shows record weather as a select and can save before weather is known", () => {
    const onSave = vi.fn();
    render(<LedgerForm categories={[]} config={directConfig} onSave={onSave} />);

    expect(screen.getByRole("combobox", { name: "天气" })).toHaveTextContent("请选择天气");
    fireEvent.change(screen.getByLabelText("当日营业额"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ weather: null }));
  });

  it("offers only the ten configured record weather values for manual selection", async () => {
    render(<LedgerForm categories={[]} config={directConfig} onSave={vi.fn()} />);

    fireEvent.pointerDown(screen.getByRole("combobox", { name: "天气" }), { button: 0, ctrlKey: false, pointerType: "mouse" });

    await waitFor(() => expect(document.querySelectorAll('[role="option"]')).toHaveLength(10));
    const weatherOptions = [...document.querySelectorAll('[role="option"]')];
    expect(weatherOptions.map((option) => option.textContent)).toEqual([
      "晴", "少云", "多云", "阴", "雾", "小雨", "中雨", "大雨", "阵雨", "雷雨",
    ]);
    expect(weatherOptions.some((option) => /未选择|请选择天气/.test(option.textContent ?? ""))).toBe(false);
  });

  it.each([
    { source: "saved record", props: { record: savedRecord({ weather: "大雪" }) } },
    { source: "automatic weather", props: { weather: { weather: "大雪", weather_code: 75, temperature_max: 2, temperature_min: -1, precipitation: 8 } } },
  ])("displays and preserves weather outside manual options from $source", async ({ props }) => {
    const onSave = vi.fn();
    render(<LedgerForm categories={[]} config={directConfig} {...props} onSave={onSave} />);

    expect(screen.getByRole("combobox", { name: "天气" })).toHaveTextContent("大雪");
    fireEvent.pointerDown(screen.getByRole("combobox", { name: "天气" }), { button: 0, ctrlKey: false, pointerType: "mouse" });
    await waitFor(() => expect(document.querySelectorAll('[role="option"]')).toHaveLength(10));
    expect([...document.querySelectorAll('[role="option"]')].map((option) => option.textContent)).not.toContain("大雪");
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());

    const directAmount = screen.queryByLabelText("当日营业额");
    if (directAmount) fireEvent.change(directAmount, { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ weather: "大雪", weather_edited: false }));
  });
});
