import { expect, it } from "vitest";

import {
  businessRecordsRangeFromAction,
  validatedBusinessRecordsAction,
} from "@/navigation/agent-actions";

it("accepts only the closed business records action contract", () => {
  expect(
    validatedBusinessRecordsAction(
      {
        type: "open_business_records",
        start_month: "2025-01",
        end_month: "2025-12",
      },
      "2026-07",
    ),
  ).toEqual({
    type: "open_business_records",
    start_month: "2025-01",
    end_month: "2025-12",
  });

  for (const value of [
    {
      type: "open_business_records",
      start_month: "2025-12",
      end_month: "2025-01",
    },
    {
      type: "open_business_records",
      start_month: "2026-08",
      end_month: "2026-08",
    },
    {
      type: "open_business_records",
      start_month: "2025-01",
      end_month: "2025-12",
      store_id: 9,
    },
    {
      type: "open_business_records",
      start_month: "2025-01",
      end_month: "2025-12",
      url: "/database",
    },
  ]) {
    expect(validatedBusinessRecordsAction(value, "2026-07")).toBeNull();
  }
});

it("uses the existing month-range semantics for the current month", () => {
  expect(
    businessRecordsRangeFromAction(
      {
        type: "open_business_records",
        start_month: "2026-06",
        end_month: "2026-07",
      },
      "2026-07-17",
    ),
  ).toEqual({
    start: "2026-06-01",
    end: "2026-07-17",
  });
});
