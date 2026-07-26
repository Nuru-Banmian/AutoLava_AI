import type { OpenBusinessRecordsAction } from "@/api/types";
import {
  customMonthRange,
  monthSelectionIssue,
  type DateRange,
} from "@/lib/business-record-ranges";

export interface AgentBusinessRecordsState {
  agentBusinessRecordsAction: OpenBusinessRecordsAction;
}

export function validatedBusinessRecordsAction(
  value: unknown,
  currentMonth: string,
): OpenBusinessRecordsAction | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  if (
    Object.keys(candidate).sort().join(",") !== "end_month,start_month,type"
    || candidate.type !== "open_business_records"
    || typeof candidate.start_month !== "string"
    || typeof candidate.end_month !== "string"
    || candidate.start_month.slice(0, 4) < "2000"
    || candidate.end_month.slice(0, 4) > "2200"
    || monthSelectionIssue(
      {
        startMonth: candidate.start_month,
        endMonth: candidate.end_month,
      },
      currentMonth,
    )
  ) {
    return null;
  }
  return {
    type: "open_business_records",
    start_month: candidate.start_month,
    end_month: candidate.end_month,
  };
}

export function businessRecordsRangeFromAction(
  action: OpenBusinessRecordsAction,
  today: string,
): DateRange {
  return customMonthRange(
    {
      startMonth: action.start_month,
      endMonth: action.end_month,
    },
    today,
  );
}
