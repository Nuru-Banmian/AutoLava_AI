import { differenceInCalendarDays, endOfMonth, format, parseISO, startOfMonth, subMonths } from "date-fns";
import type { ChartBucket } from "@/api/types";

export type RecordRangeMode = "month" | "custom";
export type AnalysisRangeMode = "current-month" | "previous-month" | "six-months" | "custom";

export interface DateRange {
  start: string;
  end: string;
}

export interface MonthSelection {
  startMonth: string;
  endMonth: string;
}

export type MonthSelectionIssue = "missing" | "invalid" | "future" | "reversed";

export interface ResolvedAnalysisRange extends DateRange {
  compareStart: string | null;
  compareEnd: string | null;
  bucket: ChartBucket;
}

const iso = (value: Date) => format(value, "yyyy-MM-dd");

const parseMonth = (month: string) => {
  if (!/^\d{4}-\d{2}$/.test(month)) throw new RangeError("month must use yyyy-MM");
  const value = parseISO(`${month}-01`);
  if (format(value, "yyyy-MM") !== month) throw new RangeError("month must use yyyy-MM");
  return value;
};

const validate = (range: DateRange) => {
  if (!range.start || !range.end || parseISO(range.start) > parseISO(range.end)) {
    throw new RangeError("start must be on or before end");
  }
  return range;
};

export function monthRange(month: string): DateRange {
  const value = parseMonth(month);
  return { start: iso(startOfMonth(value)), end: iso(endOfMonth(value)) };
}

export function monthSelectionIssue(selection: MonthSelection, currentMonth: string): MonthSelectionIssue | null {
  if (!selection.startMonth || !selection.endMonth) return "missing";
  try {
    parseMonth(selection.startMonth);
    parseMonth(selection.endMonth);
  } catch {
    return "invalid";
  }
  if (selection.startMonth > currentMonth || selection.endMonth > currentMonth) return "future";
  if (selection.startMonth > selection.endMonth) return "reversed";
  return null;
}

export function customMonthRange(selection: MonthSelection, today: string): DateRange {
  const currentMonth = today.slice(0, 7);
  const issue = monthSelectionIssue(selection, currentMonth);
  if (issue) throw new RangeError(issue);
  const start = parseMonth(selection.startMonth);
  const end = parseMonth(selection.endMonth);
  return {
    start: iso(startOfMonth(start)),
    end: selection.endMonth === currentMonth ? today : iso(endOfMonth(end)),
  };
}

export function analysisRange(
  mode: AnalysisRangeMode,
  today: string,
  custom?: DateRange,
): ResolvedAnalysisRange {
  const now = parseISO(today);
  if (mode === "custom") {
    const range = validate(custom ?? { start: "", end: "" });
    const inclusiveDays = differenceInCalendarDays(parseISO(range.end), parseISO(range.start)) + 1;
    return { ...range, compareStart: null, compareEnd: null, bucket: inclusiveDays <= 62 ? "day" : "month" };
  }

  if (mode === "current-month") {
    return {
      start: iso(startOfMonth(now)),
      end: today,
      compareStart: iso(startOfMonth(subMonths(now, 1))),
      compareEnd: iso(subMonths(now, 1)),
      bucket: "day",
    };
  }

  if (mode === "previous-month") {
    const previous = subMonths(now, 1);
    const comparison = subMonths(now, 2);
    return {
      start: iso(startOfMonth(previous)),
      end: iso(endOfMonth(previous)),
      compareStart: iso(startOfMonth(comparison)),
      compareEnd: iso(endOfMonth(comparison)),
      bucket: "day",
    };
  }

  return {
    start: iso(startOfMonth(subMonths(now, 5))),
    end: today,
    compareStart: iso(startOfMonth(subMonths(now, 11))),
    compareEnd: iso(subMonths(now, 6)),
    bucket: "month",
  };
}

export function analysisSearchParams(range: ResolvedAnalysisRange): URLSearchParams {
  const params = new URLSearchParams({ start: range.start, end: range.end, bucket: range.bucket });
  if (range.compareStart && range.compareEnd) {
    params.set("compare_start", range.compareStart);
    params.set("compare_end", range.compareEnd);
  }
  return params;
}
