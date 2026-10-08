import asyncio
import json
from importlib.resources import files
from typing import Protocol
from collections.abc import AsyncGenerator
from contextlib import aclosing

from langgraph.graph import END, START, StateGraph

from app.agents.assistant.state import AssistantState
from app.agents.providers.bailian import ModelFailure, ModelUsage, ToolCall
from app.agents.registry import capabilities
from app.agents.runtime.repository import ChatRepository
from app.core.config import Settings


class ChatModel(Protocol):
    model_name: str

    def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str | ModelUsage, None]: ...


def create_graph(model: ChatModel, storage: ChatRepository, settings: Settings,
                 *, agent_capabilities=None, memory_index=None):
    prompt = files("app.agents.assistant").joinpath("prompts.md").read_text(encoding="utf-8")
    skills, tools = capabilities() if agent_capabilities is None else agent_capabilities
    catalog = json.dumps({"enabled_skills": list(skills.metadata.values())}, ensure_ascii=False)
    schema_size = len(json.dumps(tools.schemas, ensure_ascii=False)) if hasattr(model, "stream_tools") else 0

    def context_size(messages):
        return len(json.dumps(messages, ensure_ascii=False)) + schema_size

    async def context(state: AssistantState):
        retrieval = (await memory_index.retrieve(state["scope"], state["run_id"])
                     if memory_index else {"status": "unavailable", "items": []})
        background = await storage.background(state["scope"], state["run_id"])
        background["memories"] = retrieval["items"]
        background["memory_retrieval"] = retrieval["status"]
        conversation = await storage.conversation(state["scope"])
        data = json.dumps({"store_background": background}, ensure_ascii=False)
        base = [{"role": "system", "content": prompt},
                {"role": "system", "content": catalog}, {"role": "user", "content": data}]
        messages = []
        for message in reversed(conversation.messages):
            candidate = {"role": message.role, "content": message.content}
            if context_size([*base, candidate, *reversed(messages)]) > settings.agent_context_chars:
                if not messages:
                    raise ModelFailure("context_budget")
                break
            messages.append(candidate)
        await storage.record(state["scope"], state["run_id"], "context", {
            "source": background["source"], "revision": background["revision"],
        })
        await storage.record(state["scope"], state["run_id"], "retrieval", {
            "status": retrieval["status"],
            "references": [{"id": m["id"], "version": m["version"]} for m in retrieval["items"]],
        })
        if retrieval["status"] != "available":
            await storage.record(state["scope"], state["run_id"], "delta", {
                "text": "记忆检索受限，本轮未参考长期记忆。\n\n",
            })
        return {"messages": [*base, *reversed(messages)]}

    async def generate(state: AssistantState):
        output_size = 0
        attempts = tool_count = 0
        messages = list(state["messages"])
        while attempts < settings.agent_max_steps:
            calls, text = [], ""
            for retry in range(settings.agent_max_calls):
                if attempts >= settings.agent_max_steps:
                    raise ModelFailure("step_budget")
                if context_size(messages) > settings.agent_context_chars:
                    raise ModelFailure("context_budget")
                attempts += 1
                await storage.record(state["scope"], state["run_id"], "attempt", {"number": attempts})
                try:
                    stream = (model.stream_tools(messages, tools.schemas)
                              if hasattr(model, "stream_tools") else model.stream(messages))
                    async with aclosing(stream) as chunks:
                        async for chunk in chunks:
                            if isinstance(chunk, ModelUsage):
                                await storage.record(state["scope"], state["run_id"], "usage", chunk.tokens)
                            elif isinstance(chunk, ToolCall):
                                if len(calls) >= settings.agent_max_tool_calls or any(c.id == chunk.id for c in calls):
                                    raise ModelFailure("model_format")
                                calls.append(chunk)
                            elif isinstance(chunk, str):
                                output_size += len(chunk)
                                if output_size > settings.agent_output_chars:
                                    raise ModelFailure("output_budget")
                                if chunk:
                                    text += chunk
                                    await storage.record(state["scope"], state["run_id"], "delta", {"text": chunk})
                            else:
                                raise ModelFailure("model_format")
                    break
                except ModelFailure as exc:
                    if text or calls or not exc.retryable or retry + 1 == settings.agent_max_calls:
                        raise
                    await asyncio.sleep(0.25 * (retry + 1))
            if not calls:
                if not text:
                    raise ModelFailure("model_format")
                await storage.record(state["scope"], state["run_id"], "completed", {"status": "completed"})
                return {}
            messages.append({"role": "assistant", "content": text or None,
                             "tool_calls": [call.wire() for call in calls]})
            for call in calls:
                tool_count += 1
                if tool_count > settings.agent_max_tool_calls:
                    raise ModelFailure("tool_budget")
                result = await tools.execute(call, storage, state["scope"], state["run_id"])
                # record reauthorizes after execution; reset/stopped/revoked runs cannot publish.
                await storage.record(state["scope"], state["run_id"], "tool", {
                    "name": call.name if call.name in tools.tools else "unauthorized",
                    "status": "denied" if "error" in result else "completed",
                    **({"range": result["range"]} if "range" in result else {}),
                })
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(result, ensure_ascii=False)})
        raise ModelFailure("step_budget")

    builder = StateGraph(AssistantState)
    builder.add_node("context", context)
    builder.add_node("generate", generate)
    builder.add_edge(START, "context")
    builder.add_edge("context", "generate")
    builder.add_edge("generate", END)
    return builder.compile()
