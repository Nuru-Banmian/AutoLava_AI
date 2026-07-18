import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecordPagination } from "@/components/RecordPagination";

describe("RecordPagination", () => {
  it("moves through fixed-size pages", () => {
    const onPageChange = vi.fn();
    render(<RecordPagination page={2} total={31} pageSize={15} onPageChange={onPageChange} />);

    expect(screen.getByText("第 2 / 3 页")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it("disables unavailable directions", () => {
    render(<RecordPagination page={1} total={0} pageSize={15} onPageChange={vi.fn()} />);

    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(screen.getByText("第 1 / 1 页")).toBeInTheDocument();
  });
});
