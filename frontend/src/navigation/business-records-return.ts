import type { DateRange, RecordRangeMode } from "@/lib/business-record-ranges";

export interface BusinessRecordsViewState {
  storeId: number;
  recordMode: RecordRangeMode;
  range: DateRange;
  page: number;
  selectedDate: string | null;
  mobileRecordDate: string | null;
  scrollY: number;
}

export interface LedgerLocationState {
  returnToBusinessRecords?: BusinessRecordsViewState;
}

export interface BusinessRecordsLocationState {
  restoreBusinessRecords?: BusinessRecordsViewState;
}

const recordRangeModes = new Set<RecordRangeMode>(["current-month", "previous-month", "month", "custom"]);

function isRecordRangeMode(value: unknown): value is RecordRangeMode {
  return typeof value === "string" && recordRangeModes.has(value as RecordRangeMode);
}

function isDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}

function isNullableDate(value: unknown): value is string | null {
  return value === null || isDate(value);
}

function isDateRange(value: unknown): value is DateRange {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<DateRange>;
  return isDate(candidate.start) && isDate(candidate.end) && candidate.start <= candidate.end;
}

function isBusinessRecordsViewState(value: unknown): value is BusinessRecordsViewState {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<BusinessRecordsViewState>;
  return Number.isInteger(candidate.storeId) && candidate.storeId! > 0
    && isRecordRangeMode(candidate.recordMode)
    && isDateRange(candidate.range)
    && Number.isInteger(candidate.page) && candidate.page! > 0
    && isNullableDate(candidate.selectedDate)
    && isNullableDate(candidate.mobileRecordDate)
    && typeof candidate.scrollY === "number"
    && Number.isFinite(candidate.scrollY)
    && candidate.scrollY >= 0;
}

export function ledgerReturnState(value: unknown): BusinessRecordsViewState | null {
  if (!value || typeof value !== "object" || !("returnToBusinessRecords" in value)) return null;
  const candidate = (value as LedgerLocationState).returnToBusinessRecords;
  return isBusinessRecordsViewState(candidate) ? candidate : null;
}

export function restoredBusinessRecordsState(value: unknown, storeId: number | null | undefined): BusinessRecordsViewState | null {
  if (!value || typeof value !== "object" || !("restoreBusinessRecords" in value)) return null;
  const candidate = (value as BusinessRecordsLocationState).restoreBusinessRecords;
  return isBusinessRecordsViewState(candidate) && candidate.storeId === storeId ? candidate : null;
}
