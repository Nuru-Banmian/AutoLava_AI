import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";
import { downloadBusinessRecords } from "@/lib/business-record-export";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { server.resetHandlers(); vi.restoreAllMocks(); });
afterAll(() => server.close());

it("downloads exactly the active range and revokes the object URL", async () => {
  let requested = "";
  server.use(http.get("/api/database/7/export.xlsx", ({ request }) => {
    requested = request.url;
    return new HttpResponse("xlsx", { status: 200 });
  }));
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:records");
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  const click = vi.fn();
  vi.spyOn(document, "createElement").mockReturnValue({ href: "", download: "", click } as unknown as HTMLAnchorElement);

  await downloadBusinessRecords(7, { start: "2026-07-01", end: "2026-07-31" });

  expect(new URL(requested).search).toBe("?start=2026-07-01&end=2026-07-31");
  expect(click).toHaveBeenCalledOnce();
  expect(revoke).toHaveBeenCalledWith("blob:records");
});

it("rejects a failed export without creating a download", async () => {
  server.use(http.get("/api/database/7/export.xlsx", () => HttpResponse.json({ detail: "failed" }, { status: 500 })));
  const create = vi.spyOn(URL, "createObjectURL");

  await expect(downloadBusinessRecords(7, { start: "2026-07-01", end: "2026-07-31" })).rejects.toMatchObject({ status: 500 });

  expect(create).not.toHaveBeenCalled();
});
