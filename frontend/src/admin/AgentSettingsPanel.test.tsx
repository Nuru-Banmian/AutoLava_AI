import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it } from "vitest";

import { AgentSettingsPanel } from "@/admin/AgentSettingsPanel";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPanel(isOwner: boolean) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <AgentSettingsPanel isOwner={isOwner} />
    </QueryClientProvider>,
  );
}

it("lets the final administrator persist the global Agent switch", async () => {
  let enabled = false;
  server.use(
    http.get("/api/admin/agent-settings", () => HttpResponse.json({ enabled })),
    http.patch("/api/admin/agent-settings", async ({ request }) => {
      enabled = (await request.json() as { enabled: boolean }).enabled;
      return HttpResponse.json({ enabled });
    }),
  );
  renderPanel(true);

  const toggle = await screen.findByRole("switch", {
    name: "全局启用 Agent",
  });
  expect(toggle).toHaveAttribute("aria-checked", "false");
  fireEvent.click(toggle);

  expect(await screen.findByText("Agent 已全局启用")).toBeInTheDocument();
  expect(toggle).toHaveAttribute("aria-checked", "true");
});

it("shows ordinary administrators the state without allowing changes", async () => {
  server.use(
    http.get("/api/admin/agent-settings", () =>
      HttpResponse.json({ enabled: true }),
    ),
  );
  renderPanel(false);

  const toggle = await screen.findByRole("switch", {
    name: "全局启用 Agent",
  });
  expect(toggle).toBeDisabled();
  expect(screen.getByText("仅最终管理员可以修改此设置")).toBeInTheDocument();
});
