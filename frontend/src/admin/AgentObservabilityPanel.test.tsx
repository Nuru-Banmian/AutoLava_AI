import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { AgentObservabilityPanel } from "@/admin/AgentObservabilityPanel";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.clearAllMocks();
});
afterAll(() => server.close());

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AgentObservabilityPanel />
    </QueryClientProvider>,
  );
}

describe("AgentObservabilityPanel", () => {
  it("shows sanitized run health and lets the final admin resolve an alert", async () => {
    let statusBody: unknown;
    server.use(
      http.get("/api/admin/agent-observability/runs", () =>
        HttpResponse.json([
          {
            id: 17,
            run_id: "6505b20a-a326-48c4-b536-4a86e0382826",
            role: "final_admin",
            stage: "answer",
            provider: "primary",
            model: "analysis-model",
            input_tokens: 120,
            output_tokens: 45,
            result: "success",
            error_category: null,
            latency_ms: 380,
            estimated_cost: 0.0123,
            is_fallback: true,
            created_at: "2026-07-28T12:00:00",
          },
        ]),
      ),
      http.get("/api/admin/agent-observability/alerts", () =>
        HttpResponse.json([
          {
            id: 9,
            alert_type: "service",
            provider: "primary",
            model: "analysis-model",
            error_category: "provider_5xx",
            message: "模型服务持续不可用，请检查供应商状态。",
            occurrence_count: 3,
            is_resolved: false,
            created_at: "2026-07-28T11:00:00",
            last_seen_at: "2026-07-28T12:00:00",
            resolved_at: null,
          },
        ]),
      ),
      http.patch("/api/admin/agent-observability/alerts/9", async ({ request }) => {
        statusBody = await request.json();
        return HttpResponse.json({
          id: 9,
          alert_type: "service",
          provider: "primary",
          model: "analysis-model",
          error_category: "provider_5xx",
          message: "模型服务持续不可用，请检查供应商状态。",
          occurrence_count: 3,
          is_resolved: true,
          created_at: "2026-07-28T11:00:00",
          last_seen_at: "2026-07-28T12:00:00",
          resolved_at: "2026-07-28T12:05:00",
        });
      }),
    );
    renderPanel();

    expect(await screen.findByRole("heading", { name: "Agent 运行健康" })).toBeInTheDocument();
    expect(await screen.findByText("6505b20a-a326-48c4-b536-4a86e0382826")).toBeInTheDocument();
    expect(screen.getByText("120 / 45")).toBeInTheDocument();
    expect(screen.getByText("€0.0123")).toBeInTheDocument();
    expect(screen.getByText("已使用回退")).toBeInTheDocument();
    expect(screen.getByText(/primary \/ analysis-model · 累计 3 次/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "标记告警 9 为已解决" }));

    await waitFor(() => expect(statusBody).toEqual({ status: "resolved" }));
    await waitFor(() =>
      expect(screen.getByText("已解决", { selector: "span" })).toBeInTheDocument(),
    );
  });

  it("shows an explicit empty state without exposing ordinary system status", async () => {
    server.use(
      http.get("/api/admin/agent-observability/runs", () => HttpResponse.json([])),
      http.get("/api/admin/agent-observability/alerts", () => HttpResponse.json([])),
    );
    renderPanel();

    expect(await screen.findByText("还没有 Agent 运行统计")).toBeInTheDocument();
    expect(screen.getByText("当前没有 Agent 告警")).toBeInTheDocument();
  });
});
