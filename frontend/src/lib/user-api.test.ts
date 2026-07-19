import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import * as userApi from "@/lib/user-api";

const parseWholeAmount = (userApi as typeof userApi & {
  parseWholeAmount(value: string): { value: number } | { error: string };
}).parseWholeAmount;
const formatWholeEuro = (userApi as typeof userApi & {
  formatWholeEuro(value: number): string;
}).formatWholeEuro;

describe("user API helpers", () => {
  it("invalidates only exact store positions and not a recent-days collision", async () => {
    const client = new QueryClient();
    const keys = [
      ["ledger", "recent", 1, 7], ["ledger", "recent", 7, 7], ["ledger", "record", 7, "2026-07-14"],
      ["ledgerMonth", 7, "2026-07"], ["ledgerMonth", 8, "2026-07"], ["database", "records", 7, "page=1"], ["charts", 7, "start=x"],
      ["dashboard", 7], ["categoryCatalog", 7, "2026-07-14"], ["weather", 7, "2026-07-14"],
    ] as const;
    keys.forEach((key) => client.setQueryData(key, true));
    await userApi.invalidateUserData(client, 7);
    expect(client.getQueryState(["ledger", "recent", 1, 7])?.isInvalidated).toBe(false);
    for (const key of [keys[1], keys[2], keys[3], keys[5], keys[6], keys[7], keys[8]]) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    expect(client.getQueryState(keys[4])?.isInvalidated).toBe(false);
    expect(client.getQueryState(["weather", 7, "2026-07-14"])?.isInvalidated).toBe(false);
  });

  it("parses only canonical non-negative whole amounts", () => {
    expect(parseWholeAmount("123")).toEqual({ value: 123 });
    for (const value of ["", "-1", "1.2", "1e2", " 1", "1 "]) {
      expect(parseWholeAmount(value)).toEqual({ error: "金额必须是大于等于 0 的整数" });
    }
  });

  it("rejects whole amounts beyond JavaScript's safe integer range", () => {
    expect(parseWholeAmount("9007199254740992")).toEqual({ error: "金额超出可保存范围" });
  });

  it("formats whole euros without decimal cents", () => {
    expect(formatWholeEuro(1234)).toBe("€1.234");
  });
});
