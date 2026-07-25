import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { DatabaseBackupPanel } from "@/admin/DatabaseBackupPanel";
import { downloadDatabaseBackup } from "@/lib/database-backup";

vi.mock("@/lib/database-backup", () => ({
  downloadDatabaseBackup: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

it("downloads only after warning about every sensitive data category", async () => {
  const user = userEvent.setup();
  render(<DatabaseBackupPanel />);

  await user.click(screen.getByRole("button", { name: "下载数据库备份" }));
  const dialog = screen.getByRole("alertdialog", { name: "下载完整数据库备份？" });
  expect(dialog).toHaveTextContent("经营数据");
  expect(dialog).toHaveTextContent("账号信息");
  expect(dialog).toHaveTextContent("密码哈希");
  expect(dialog.querySelector('input[type="password"]')).toBeNull();
  expect(downloadDatabaseBackup).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "取消" }));
  expect(downloadDatabaseBackup).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "下载数据库备份" }));
  await user.click(screen.getByRole("button", { name: "确认并下载" }));

  expect(downloadDatabaseBackup).toHaveBeenCalledOnce();
});
