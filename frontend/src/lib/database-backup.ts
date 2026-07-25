import { ApiError } from "@/api/client";

function attachmentFilename(disposition: string | null): string {
  const encoded = disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      // Fall through to the plain filename or safe default.
    }
  }
  return disposition?.match(/filename="?([^";]+)"?/i)?.[1]
    ?? "autolava-backup.sqlite3";
}

export async function downloadDatabaseBackup(): Promise<void> {
  const response = await fetch("/api/admin/database-backup", {
    credentials: "include",
  });
  if (!response.ok) {
    throw new ApiError(response.status, "数据库备份下载失败，请重试");
  }

  const objectUrl = URL.createObjectURL(await response.blob());
  try {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = attachmentFilename(response.headers.get("content-disposition"));
    anchor.click();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
