import { fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, Link, RouterProvider } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { UnsavedChangesProvider, UnsavedRouteGuard, useUnsavedChanges } from "@/navigation/UnsavedChanges";

function GuardHarness() {
  const { markDirty } = useUnsavedChanges();
  return <><UnsavedRouteGuard /><button onClick={() => markDirty(true)}>修改</button><Link to="/next">离开</Link></>;
}

function BeforeUnloadHarness() {
  const { markDirty } = useUnsavedChanges();
  return <><button onClick={() => markDirty(true)}>设为已修改</button><button onClick={() => markDirty(false)}>设为已保存</button></>;
}

function CompetingTransitionsHarness({ first, second, cancelSecond }: { first(): void; second(): void; cancelSecond(): void }) {
  const { markDirty, requestTransition } = useUnsavedChanges();
  return <><button onClick={() => markDirty(true)}>修改</button><button onClick={() => requestTransition(first)}>第一个动作</button><button onClick={() => requestTransition(second, cancelSecond)}>第二个动作</button></>;
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

  it("keeps one active transition and explicitly cancels a competing request", async () => {
    const first = vi.fn();
    const second = vi.fn();
    const cancelSecond = vi.fn();
    render(<UnsavedChangesProvider><CompetingTransitionsHarness first={first} second={second} cancelSecond={cancelSecond} /></UnsavedChangesProvider>);

    fireEvent.click(screen.getByRole("button", { name: "修改" }));
    fireEvent.click(screen.getByRole("button", { name: "第一个动作" }));
    fireEvent.click(screen.getByRole("button", { name: "第二个动作", hidden: true }));

    expect(cancelSecond).toHaveBeenCalledOnce();
    fireEvent.click(await screen.findByRole("button", { name: "放弃修改" }));
    expect(first).toHaveBeenCalledOnce();
    expect(second).not.toHaveBeenCalled();
  });
});
