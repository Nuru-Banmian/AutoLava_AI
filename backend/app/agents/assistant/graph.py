import asyncio
from importlib.resources import files
from typing import Protocol
from collections.abc import AsyncGenerator
from contextlib import aclosing

from langgraph.graph import END, START, StateGraph

from app.agents.assistant.state import AssistantState
from app.agents.providers.bailian import ModelFailure, ModelUsage
from app.agents.runtime.repository import ChatRepository
from app.core.config import Settings


class ChatModel(Protocol):
    model_name: str

    def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str | ModelUsage, None]: ...


def create_graph(model: ChatModel, storage: ChatRepository, settings: Settings):
    prompt = files("app.agents.assistant").joinpath("prompts.md").read_text(encoding="utf-8")

    async def context(state: AssistantState):
        conversation = await storage.conversation(state["scope"])
        remaining = settings.agent_context_chars - len(prompt)
        messages = []
        for message in reversed(conversation.messages):
            if len(message.content) > remaining:
                break
            messages.append({"role": message.role, "content": message.content})
            remaining -= len(message.content)
        return {"messages": [{"role": "system", "content": prompt}, *reversed(messages)]}

    async def generate(state: AssistantState):
        output_size = 0
        for attempt in range(settings.agent_max_calls):
            await storage.record(state["scope"], state["run_id"], "attempt", {"number": attempt + 1})
            try:
                async with aclosing(model.stream(state["messages"])) as chunks:
                    async for chunk in chunks:
                        if isinstance(chunk, ModelUsage):
                            await storage.record(state["scope"], state["run_id"], "usage", chunk.tokens)
                            continue
                        if not isinstance(chunk, str):
                            raise ModelFailure("model_format")
                        output_size += len(chunk)
                        if output_size > settings.agent_output_chars:
                            raise ModelFailure("output_budget")
                        if chunk:
                            await storage.record(state["scope"], state["run_id"], "delta", {"text": chunk})
                if not output_size:
                    raise ModelFailure("model_format")
                await storage.record(state["scope"], state["run_id"], "completed", {"status": "completed"})
                return {}
            except ModelFailure as exc:
                if output_size or not exc.retryable or attempt + 1 == settings.agent_max_calls:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1))
        return {}

    builder = StateGraph(AssistantState)
    builder.add_node("context", context)
    builder.add_node("generate", generate)
    builder.add_edge(START, "context")
    builder.add_edge("context", "generate")
    builder.add_edge("generate", END)
    return builder.compile()
