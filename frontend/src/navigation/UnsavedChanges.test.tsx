import { fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, Link, RouterProvider } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { UnsavedChangesProvider, UnsavedRouteGuard, useUnsavedChanges } from "@/navigation/UnsavedChanges";

function GuardHarness() {
  const { markDirty } = useUnsavedChanges();
  return <><UnsavedRouteGuard /><button onClick={() => markDirty(true)}>修改</button><Link to="/next">离开</Link></>;
}

function BeforeUnloadHarness() {
  const { markDirty } = useUnsavedChanges();
  return <><button onClick={() => markDirty(true)}>设为已修改</button><button onClick={() => markDirty(false)}>设为已保存</button></>;
}

describe("UnsavedChangesProvider", () => {
  it("blocks route navigation until the user confirms discarding edits", async () => {
    const router = createMemoryRouter([
      { path: "/", element: <UnsavedChangesProvider><GuardHarness /></UnsavedChangesProvider> },
      { path: "/next", element: <p>下一页</p> },
    ], { initialEntries: ["/"] });
    render(<RouterProvider router={router} />);

    fireEvent.click(screen.getByRole("button", { name: "修改" }));
    fireEvent.click(screen.getByRole("link", { name: "离开" }));
    expect(await screen.findByRole("alertdialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByRole("link", { name: "离开" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: "离开" }));
    fireEvent.click(await screen.findByRole("button", { name: "放弃修改" }));
    expect(await screen.findByText("下一页")).toBeInTheDocument();
  });

  it("registers beforeunload only while changes are dirty", () => {
    render(<UnsavedChangesProvider><BeforeUnloadHarness /></UnsavedChangesProvider>);
    const cleanEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanEvent);
    expect(cleanEvent.defaultPrevented).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "设为已修改" }));
    const dirtyEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirtyEvent);
    expect(dirtyEvent.defaultPrevented).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "设为已保存" }));
    const savedEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(savedEvent);
    expect(savedEvent.defaultPrevented).toBe(false);
  });
});
