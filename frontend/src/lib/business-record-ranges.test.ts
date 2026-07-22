import { describe, expect, it } from "vitest";
import { analysisRange, analysisSearchParams, customMonthRange, monthRange, recordRange } from "@/lib/business-record-ranges";

describe("business record ranges", () => {
  it("uses full calendar months for record browsing", () => {
    expect(recordRange("current-month", "2026-07-17")).toEqual({ start: "2026-07-01", end: "2026-07-31" });
    expect(recordRange("previous-month", "2026-01-10")).toEqual({ start: "2025-12-01", end: "2025-12-31" });
  });

  it("resolves selected and custom month boundaries", () => {
    expect(monthRange("2025-12")).toEqual({ start: "2025-12-01", end: "2025-12-31" });
    expect(customMonthRange("2026-05", "2026-06", "2026-07-17")).toEqual({ start: "2026-05-01", end: "2026-06-30" });
    expect(customMonthRange("2026-05", "2026-07", "2026-07-17")).toEqual({ start: "2026-05-01", end: "2026-07-17" });
    expect(() => customMonthRange("2026-08", "2026-08", "2026-07-17")).toThrow(RangeError);
    expect(() => customMonthRange("2026-07", "2026-06", "2026-07-17")).toThrow(RangeError);
  });

  it("compares month-to-date with the same available prior-month period", () => {
    expect(analysisRange("current-month", "2026-03-31")).toEqual({
      start: "2026-03-01",
      end: "2026-03-31",
      compareStart: "2026-02-01",
      compareEnd: "2026-02-28",
      bucket: "day",
    });
  });

  it("uses full previous months and a six-month shifted comparison", () => {
    expect(analysisRange("previous-month", "2026-03-17")).toEqual({
      start: "2026-02-01",
      end: "2026-02-28",
      compareStart: "2026-01-01",
      compareEnd: "2026-01-31",
      bucket: "day",
    });
    expect(analysisRange("six-months", "2026-02-10")).toEqual({
      start: "2025-09-01",
      end: "2026-02-10",
      compareStart: "2025-03-01",
      compareEnd: "2025-08-10",
      bucket: "month",
    });
    expect(analysisRange("six-months", "2026-08-31").compareEnd).toBe("2026-02-28");
  });

  it("switches custom aggregation after 62 inclusive days and omits comparison", () => {
    expect(analysisRange("custom", "2026-07-17", { start: "2026-01-01", end: "2026-03-03" }).bucket).toBe("day");
    expect(analysisRange("custom", "2026-07-17", { start: "2026-01-01", end: "2026-03-04" })).toMatchObject({
      compareStart: null,
      compareEnd: null,
      bucket: "month",
    });
    expect(() => analysisRange("custom", "2026-07-17", { start: "2026-07-18", end: "2026-07-17" })).toThrow(RangeError);
  });

  it("serializes comparison only when present", () => {
    const params = analysisSearchParams(analysisRange("current-month", "2026-07-17"));
    expect(params.toString()).toBe("start=2026-07-01&end=2026-07-17&bucket=day&compare_start=2026-06-01&compare_end=2026-06-17");
  });
});
