import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BriefingCard } from "@/api/types";
import { BriefingCards } from "@/components/BriefingCards";

const earlyCloseCard: BriefingCard = {
  card_type: "yesterday",
  state: "early_closed",
  revenue: 150,
  weather: null,
  weekday: null,
  temperature_max: null,
  temperature_min: null,
  precipitation: null,
  hint: null,
  generated_at: "2026-07-15T08:00:00Z",
  timestamp_status: "utc",
};

describe("BriefingCards", () => {
  it("shows an early close with the revenue already earned", () => {
    render(<BriefingCards cards={[earlyCloseCard]} yesterdayHref="/ledger?date=2026-07-14" />);

    expect(screen.getByText("昨日提前休息")).toBeInTheDocument();
    expect(screen.getByText("€150")).toBeInTheDocument();
    expect(screen.queryByText(/天气停业/)).not.toBeInTheDocument();
  });
});
