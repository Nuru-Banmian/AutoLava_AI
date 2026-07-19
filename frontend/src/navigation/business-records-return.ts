import type { AnalysisRangeMode, DateRange, RecordRangeMode } from "@/lib/business-record-ranges";

export interface BusinessAnalysisViewState {
  mode: AnalysisRangeMode;
  custom: DateRange;
}

export interface BusinessRecordsViewState {
  storeId: number;
  recordMode: RecordRangeMode;
  range: DateRange;
  page: number;
  selectedDate: string | null;
  mobileRecordDate: string | null;
  analysis: BusinessAnalysisViewState;
  scrollY: number;
}

export interface LedgerLocationState {
  returnToBusinessRecords?: BusinessRecordsViewState;
}

export interface BusinessRecordsLocationState {
  restoreBusinessRecords?: BusinessRecordsViewState;
}

const recordRangeModes = new Set<RecordRangeMode>(["current-month", "previous-month", "custom"]);
const analysisRangeModes = new Set<AnalysisRangeMode>(["current-month", "previous-month", "six-months", "custom"]);

function isRecordRangeMode(value: unknown): value is RecordRangeMode {
  return typeof value === "string" && recordRangeModes.has(value as RecordRangeMode);
}

function isAnalysisRangeMode(value: unknown): value is AnalysisRangeMode {
  return typeof value === "string" && analysisRangeModes.has(value as AnalysisRangeMode);
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
  const analysis = candidate.analysis as Partial<BusinessAnalysisViewState> | undefined;
  return Number.isInteger(candidate.storeId) && candidate.storeId! > 0
    && isRecordRangeMode(candidate.recordMode)
    && isDateRange(candidate.range)
    && Number.isInteger(candidate.page) && candidate.page! > 0
    && isNullableDate(candidate.selectedDate)
    && isNullableDate(candidate.mobileRecordDate)
    && Boolean(analysis)
    && isAnalysisRangeMode(analysis?.mode)
    && isDateRange(analysis?.custom)
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
