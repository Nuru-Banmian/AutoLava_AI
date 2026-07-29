import json

import respx
from httpx import Response
from pydantic import SecretStr

from app.core.config import Settings
from app.services.agent_model import BailianOpenAIModelAdapter


@respx.mock
async def test_bailian_adapter_uses_openai_compatible_chat_contract() -> None:
    route = respx.post(
        "https://dashscope.example/compatible-mode/v1/chat/completions"
    ).mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "基础回答"}}
                ]
            },
        )
    )
    adapter = BailianOpenAIModelAdapter(
        Settings(
            agent_model_endpoint="https://dashscope.example/compatible-mode/v1",
            agent_model_region="eu-central-1",
            agent_model_id="qwen-test",
            agent_model_api_key=SecretStr("secret"),
        )
    )
    messages = [
        {"role": "system", "content": "可信门店上下文"},
        {"role": "user", "content": "本月经营怎么样？"},
    ]

    answer = await adapter.complete(messages)

    assert answer == "基础回答"
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer secret"
    assert request.headers["x-dashscope-region"] == "eu-central-1"
    assert json.loads(request.content) == {
        "model": "qwen-test",
        "messages": messages,
    }


@respx.mock
async def test_bailian_adapter_streams_openai_compatible_answer_deltas() -> None:
    route = respx.post(
        "https://dashscope.example/compatible-mode/v1/chat/completions"
    ).mock(
        return_value=Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":" second"}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )
    )
    adapter = BailianOpenAIModelAdapter(
        Settings(
            agent_model_endpoint="https://dashscope.example/compatible-mode/v1",
            agent_model_region="eu-central-1",
            agent_model_id="qwen-test",
            agent_model_api_key=SecretStr("secret"),
        )
    )
    messages = [{"role": "user", "content": "stream this"}]

    chunks = [chunk async for chunk in adapter.stream(messages)]

    assert chunks == ["first", " second"]
    assert json.loads(route.calls.last.request.content) == {
        "model": "qwen-test",
        "messages": messages,
        "stream": True,
    }
