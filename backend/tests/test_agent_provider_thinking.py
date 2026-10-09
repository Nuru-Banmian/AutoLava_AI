"""Bounded chat must not spend its default deadline on hidden Qwen reasoning."""
import json

import httpx
import pytest
import respx

from app.agents.providers.bailian import BailianChat, ToolCall
from app.core.config import Settings


@pytest.mark.parametrize("model,override,expected", [
    ("qwen3.6-plus", None, False),
    ("qwen3.6-plus", True, True),
    ("qwen3.6-plus", False, False),
    ("other-compatible-model", None, None),
])
async def test_chat_thinking_wire_is_explicit_and_configurable(model, override, expected):
    values = {"agent_chat_enable_thinking": override} if override is not None else {}
    settings = Settings(_env_file=None, agent_chat_base_url="https://bailian.test/v1",
                        agent_chat_api_key="test-only-key", agent_chat_model=model, **values)
    body = 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
    body += 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    body += 'data: [DONE]\n\n'
    with respx.mock() as mock:
        request = mock.post("https://bailian.test/v1/chat/completions").mock(
            return_value=httpx.Response(200, text=body),
        )
        assert [part async for part in BailianChat(settings).stream([])] == ["你好"]
        wire = json.loads(request.calls[0].request.content)
        assert wire.get("enable_thinking") is expected


async def test_complete_tool_call_accepts_provider_stop_terminator():
    settings = Settings(_env_file=None, agent_chat_base_url="https://bailian.test/v1",
                        agent_chat_api_key="test-only-key", agent_chat_model="qwen-plus")
    body = 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"m1","function":{"name":"propose_memory","arguments":"{\\\"action\\\":\\\"reject\\\"}"}}]}}]}\n\n'
    body += 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    body += 'data: {"choices":[],"usage":{"total_tokens":3}}\n\n'
    body += 'data: [DONE]\n\n'
    with respx.mock() as mock:
        mock.post("https://bailian.test/v1/chat/completions").mock(return_value=httpx.Response(200, text=body))
        parts = [part async for part in BailianChat(settings, required_tool="propose_memory").stream_tools(
            [], [{"function": {"name": "propose_memory"}}])]
        calls = [part for part in parts if isinstance(part, ToolCall)]
        assert calls == [ToolCall("m1", "propose_memory", '{"action":"reject"}')]
