// @vitest-environment node

import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createServer, type ViteDevServer } from "vite";

import globalSetup from "../../tests/global-setup";

vi.mock("vite", () => ({ createServer: vi.fn() }));

function mockServer(options: { closeError?: Error; listenError?: Error } = {}) {
  const listen = vi.fn(async () => {
    if (options.listenError) throw options.listenError;
  });
  const close = vi.fn(async () => {
    if (options.closeError) throw options.closeError;
  });
  vi.mocked(createServer).mockResolvedValue({ close, listen } as unknown as ViteDevServer);
  return { close, listen };
}

afterEach(() => vi.clearAllMocks());

describe("Playwright Vite lifecycle", () => {
  it("uses the frontend directory regardless of the caller working directory", async () => {
    const expectedRoot = resolve(fileURLToPath(new URL("../..", import.meta.url)));
    mockServer();

    const teardown = await globalSetup();

    expect(createServer).toHaveBeenCalledWith(expect.objectContaining({ root: expectedRoot }));
    await teardown();
  });

  it("closes the Vite server and preserves the listen error when startup fails", async () => {
    const listenError = new Error("port is busy");
    const { close } = mockServer({ listenError });

    await expect(globalSetup()).rejects.toBe(listenError);
    expect(close).toHaveBeenCalledOnce();
  });

  it("preserves both startup and cleanup errors", async () => {
    const listenError = new Error("plugin startup failed");
    const closeError = new Error("watcher cleanup failed");
    mockServer({ closeError, listenError });

    const error = await globalSetup().catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(AggregateError);
    expect((error as AggregateError).errors).toEqual([listenError, closeError]);
  });

  it("returns an idempotent teardown that propagates close errors", async () => {
    const closeError = new Error("close failed");
    const { close } = mockServer({ closeError });
    const teardown = await globalSetup();

    await expect(teardown()).rejects.toBe(closeError);
    await expect(teardown()).rejects.toBe(closeError);
    expect(close).toHaveBeenCalledOnce();
  });
});
