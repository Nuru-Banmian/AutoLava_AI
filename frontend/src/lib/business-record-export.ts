import { ApiError } from "@/api/client";
import type { LedgerStatus } from "@/api/types";
import type { DateRange } from "@/lib/business-record-ranges";

export async function downloadBusinessRecords(
  storeId: number,
  range: DateRange,
  status?: LedgerStatus | null,
): Promise<void> {
  const params = new URLSearchParams({ start: range.start, end: range.end });
  if (status) params.set("status", status);
  const response = await fetch(`/api/database/${storeId}/export.xlsx?${params.toString()}`, {
    credentials: "include",
  });
  if (!response.ok) throw new ApiError(response.status, "导出失败，请重试");

  const objectUrl = URL.createObjectURL(await response.blob());
  try {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = `营业记录-${range.start}-${range.end}.xlsx`;
    anchor.click();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
