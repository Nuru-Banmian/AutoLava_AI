import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { canonicalAmount, chartNumber, formatMoney, invalidateUserData } from "@/lib/user-api";

describe("user API helpers", () => {
  it("invalidates only exact store positions and not a recent-days collision", async () => {
    const client = new QueryClient();
    const keys = [
      ["ledger", "recent", 1, 7], ["ledger", "recent", 7, 7], ["ledger", "record", 7, "2026-07-14"],
      ["database", "records", 7, "page=1"], ["database", "history", 7], ["charts", 7, "start=x"],
      ["dashboard", 7], ["categoryCatalog", 7, "2026-07-14"], ["weather", 7, "2026-07-14"],
    ] as const;
    keys.forEach((key) => client.setQueryData(key, true));
    await invalidateUserData(client, 7);
    expect(client.getQueryState(["ledger", "recent", 1, 7])?.isInvalidated).toBe(false);
    for (const key of keys.slice(1, 8)) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    expect(client.getQueryState(["weather", 7, "2026-07-14"])?.isInvalidated).toBe(false);
  });

  it("canonicalizes valid decimal input and rejects values outside NUMERIC(12,2)", () => {
    expect(canonicalAmount("12,3")).toEqual({ value: "12.30" });
    expect(canonicalAmount("9999999999.99")).toEqual({ value: "9999999999.99" });
    for (const value of ["", "nope", "-1", "1.234", "9999999999.999", "10000000000.00"]) {
      expect(canonicalAmount(value)).toEqual({ error: "请输入 0 至 9999999999.99 之间、最多两位小数的金额" });
    }
  });

  it("formats decimal strings without IEEE-754 precision loss and safely projects chart values", () => {
    expect(formatMoney("9007199254740993.10")).toBe("€9007199254740993.10");
    expect(chartNumber("9007199254740993.10")).toBe(Number.MAX_SAFE_INTEGER);
    expect(chartNumber("-9007199254740993.10")).toBe(-Number.MAX_SAFE_INTEGER);
  });
});
