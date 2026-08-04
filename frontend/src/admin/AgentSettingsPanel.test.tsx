import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { AgentSettingsPanel } from "@/admin/AgentSettingsPanel";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AgentSettingsPanel />
    </QueryClientProvider>,
  );
}

describe("AgentSettingsPanel", () => {
  it("shows readiness without exposing model connection values and blocks an incomplete enable", async () => {
    server.use(
      http.get("/api/agent/admin/settings", () => HttpResponse.json({
        enabled: false,
        model_config_ready: false,
      })),
    );
    renderPanel();

    expect(await screen.findByText("模型配置不完整")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "全系统启用数据分析 Agent" })).toBeDisabled();
    expect(document.body).not.toHaveTextContent("endpoint");
    expect(document.body).not.toHaveTextContent("model-id");
    expect(document.body).not.toHaveTextContent("api-key");
  });

  it("lets the final administrator control the only global switch", async () => {
    let enabled = false;
    server.use(
      http.get("/api/agent/admin/settings", () => HttpResponse.json({
        enabled,
        model_config_ready: true,
      })),
      http.patch("/api/agent/admin/settings", async ({ request }) => {
        enabled = (await request.json() as { enabled: boolean }).enabled;
        return HttpResponse.json({ enabled, model_config_ready: true });
      }),
    );
    renderPanel();

    const toggle = await screen.findByRole("checkbox", { name: "全系统启用数据分析 Agent" });
    expect(toggle).toBeEnabled();
    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).toBeChecked());
    expect(screen.getByRole("status")).toHaveTextContent("数据分析 Agent 已启用");
  });
});
