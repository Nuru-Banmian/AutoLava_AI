import asyncio
from contextlib import aclosing
from importlib.resources import files
import json

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agents.memory_curator.state import CuratorState
from app.agents.providers.bailian import ModelFailure, ModelUsage, ToolCall
from app.agents.tools.memory_tools import MemoryProposal
from app.agents.registry import memory_capabilities


def create_memory_graph(model, service, settings, *, agent_capabilities=None):
    prompt = files("app.agents.memory_curator").joinpath("prompts.md").read_text(encoding="utf-8")
    tools = memory_capabilities() if agent_capabilities is None else agent_capabilities
    enabled = {tool["function"]["name"] for tool in tools}
    if enabled - {"propose_memory"}:
        raise ValueError("Memory curator capabilities exceed its proposal authorization")

    async def propose(state):
        snapshot = await service.snapshot(state["scope"], state["run_id"])
        messages = [{"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)}]
        if len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(tools)) > settings.agent_memory_context_chars:
            raise ModelFailure("memory_context_budget")
        for attempt in range(settings.agent_memory_max_calls):
            await service.storage.record(state["scope"], state["run_id"], "memory_attempt", {
                "number": attempt + 1, "model": model.model_name,
            })
            calls, size = [], 0
            try:
                async with aclosing(model.stream_tools(messages, tools)) as chunks:
                    async for chunk in chunks:
                        if isinstance(chunk, ToolCall):
                            calls.append(chunk)
                            size += len(chunk.arguments)
                            if len(calls) > 1 or chunk.name not in enabled:
                                raise ModelFailure("memory_invalid_proposal")
                        elif isinstance(chunk, str):
                            size += len(chunk)
                        elif isinstance(chunk, ModelUsage):
                            await service.storage.record(state["scope"], state["run_id"], "memory_usage", chunk.tokens)
                        else:
                            raise ModelFailure("memory_invalid_proposal")
                        if size > settings.agent_memory_output_chars:
                            raise ModelFailure("memory_output_budget")
                if len(calls) != 1:
                    raise ModelFailure("memory_invalid_proposal")
                try:
                    proposal = MemoryProposal.model_validate_json(calls[0].arguments)
                except ValidationError as exc:
                    raise ModelFailure("memory_invalid_proposal") from exc
                return {"snapshot": snapshot, "result": await service.commit(
                    state["scope"], state["run_id"], snapshot, proposal,
                )}
            except ModelFailure as exc:
                if calls or not exc.retryable or attempt + 1 >= settings.agent_memory_max_calls:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1))
        raise ModelFailure("memory_invalid_proposal")

    builder = StateGraph(CuratorState)
    builder.add_node("propose", propose)
    builder.add_edge(START, "propose")
    builder.add_edge("propose", END)
    return builder.compile()
