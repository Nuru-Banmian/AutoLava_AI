import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import {
  useAgentConversation,
  useAgentCurrentStore,
  useResetAgentConversation,
  useSendAgentMessage,
} from "@/lib/agent";
import { AgentPage } from "@/pages/AgentPage";
import { useStore } from "@/stores/StoreProvider";

vi.mock("@/lib/agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/agent")>();
  return {
    ...actual,
    useAgentConversation: vi.fn(),
    useAgentCurrentStore: vi.fn(),
    useResetAgentConversation: vi.fn(),
    useSendAgentMessage: vi.fn(),
  };
});
vi.mock("@/stores/StoreProvider", () => ({ useStore: vi.fn() }));

beforeEach(() => {
  vi.mocked(useStore).mockReturnValue({
    selected: { id: 7, name: "经营背景门店", timezone: "Europe/Rome" },
  } as ReturnType<typeof useStore>);
  vi.mocked(useAgentCurrentStore).mockReturnValue({
    data: { store_id: 7, store_name: "经营背景门店" },
    isPending: false,
    isError: false,
  } as unknown as ReturnType<typeof useAgentCurrentStore>);
  vi.mocked(useAgentConversation).mockReturnValue({
    data: {
      conversation_id: 3,
      store_id: 7,
      store_name: "经营背景门店",
      messages: [],
      latest_turn: {
        id: 9,
        status: "completed",
        error_message: null,
        started_at: "2026-07-29T10:00:00",
        finished_at: "2026-07-29T10:00:01",
        investigation_cards: [
          {
            operation: "按经营背景分组",
            range_start: "2026-07-06",
            range_end: "2026-07-09",
            filters: ["分组维度：记录天气"],
            status: "completed",
          },
        ],
      },
    },
    isPending: false,
    isError: false,
  } as unknown as ReturnType<typeof useAgentConversation>);
  vi.mocked(useSendAgentMessage).mockReturnValue({
    isPending: false,
    isError: false,
    mutate: vi.fn(),
  } as unknown as ReturnType<typeof useSendAgentMessage>);
  vi.mocked(useResetAgentConversation).mockReturnValue({
    isPending: false,
    isError: false,
    mutate: vi.fn(),
  } as unknown as ReturnType<typeof useResetAgentConversation>);
});

it("shows investigation ranges and filters without event or reasoning content", () => {
  render(<AgentPage />);

  const cards = screen.getByRole("region", { name: "调查过程" });
  expect(within(cards).getByText("按经营背景分组")).toBeInTheDocument();
  expect(within(cards).getByText("2026-07-06 至 2026-07-09"))
    .toBeInTheDocument();
  expect(within(cards).getByText("分组维度：记录天气")).toBeInTheDocument();
  expect(within(cards).queryByText(/学校活动|道路施工|分类推理/))
    .not.toBeInTheDocument();
});

it("shows investigation cards received during the live turn", () => {
  vi.mocked(useSendAgentMessage).mockReturnValue({
    isPending: false,
    isError: false,
    mutate: vi.fn(({ onEvent }) => {
      onEvent({
        type: "investigation_card",
        turn_id: 10,
        card: {
          operation: "查看每日台账明细",
          range_start: "2026-07-01",
          range_end: "2026-07-31",
          filters: ["仅有事件"],
          status: "completed",
        },
      });
    }),
  } as unknown as ReturnType<typeof useSendAgentMessage>);
  render(<AgentPage />);

  fireEvent.change(screen.getByRole("textbox", { name: "向 Agent 提问" }), {
    target: { value: "调查本月事件" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  const cards = screen.getByRole("region", { name: "调查过程" });
  expect(within(cards).getByText("查看每日台账明细")).toBeInTheDocument();
  expect(within(cards).getByText("2026-07-01 至 2026-07-31"))
    .toBeInTheDocument();
  expect(within(cards).getByText("仅有事件")).toBeInTheDocument();
});
