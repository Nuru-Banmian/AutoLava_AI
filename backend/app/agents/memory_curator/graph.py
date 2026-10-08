import asyncio
from contextlib import aclosing
from importlib.resources import files
import json

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agents.memory_curator.state import CuratorState
from app.agents.providers.bailian import ModelFailure, ModelUsage, ToolCall
from app.agents.tools.memory_tools import MemoryProposal, background_tools
from app.agents.registry import memory_capabilities


def create_memory_graph(model, service, settings, *, agent_capabilities=None, jobs=None):
    prompt = files("app.agents.memory_curator").joinpath("prompts.md").read_text(encoding="utf-8")
    tools = memory_capabilities() if agent_capabilities is None else agent_capabilities
    enabled = {tool["function"]["name"] for tool in tools}
    if enabled - {"propose_memory"}:
        raise ValueError("Memory curator capabilities exceed its proposal authorization")

    async def propose(state):
        job_id = state.get("job_id")
        snapshot = (await jobs.snapshot(state["scope"], job_id) if job_id is not None
                    else await service.snapshot(state["scope"], state["run_id"]))
        proposal_tools = background_tools(tools, snapshot["memories"]) if job_id is not None else tools
        model_snapshot = snapshot
        if job_id is not None:
            # Keep the complete authority snapshot for commit-time equality checks.
            model_snapshot = {**snapshot,
                "memories": [m for m in snapshot["memories"] if m["status"] == "active"],
                "pending_candidates": [m for m in snapshot["memories"] if m["status"] == "pending_confirmation"],
            }
        async def record(kind, payload):
            if job_id is not None:
                await jobs.record(state["scope"], job_id, kind, payload)
            else:
                await service.storage.record(state["scope"], state["run_id"], kind, payload)
        mode = (
            "本轮是后台普通对话整理（mode=background），不是显式记忆指令。"
            "save/duplicate/update/conflict/infer 必须提供 evidence，逐字引用本轮 input；"
            "save/update 的 content 必须等于 evidence。reject 可以不提供 evidence。"
            if job_id is not None else
            "本轮是显式记忆指令，不是后台整理。content 必须逐字等于去掉指令前缀后的 input。"
            "禁止提供 evidence；duplicate 必须提供 target_id/target_version。"
            "conflict 若与现有有效记忆冲突，应提供其 target_id/target_version；"
            "没有对应有效记忆时不提供 target。save/reject 不提供 target。"
        )
        messages = [{"role": "system", "content": prompt},
                    {"role": "system", "content": mode},
                    {"role": "user", "content": json.dumps(model_snapshot, ensure_ascii=False)}]
        if len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(proposal_tools)) > settings.agent_memory_context_chars:
            raise ModelFailure("memory_context_budget")
        for attempt in range(settings.agent_memory_max_calls):
            await record("memory_attempt", {
                "number": attempt + 1, "model": model.model_name,
            })
            calls, size = [], 0
            try:
                async with aclosing(model.stream_tools(messages, proposal_tools)) as chunks:
                    async for chunk in chunks:
                        if isinstance(chunk, ToolCall):
                            calls.append(chunk)
                            size += len(chunk.arguments)
                            if len(calls) > 1 or chunk.name not in enabled:
                                raise ModelFailure("memory_invalid_proposal")
                        elif isinstance(chunk, str):
                            size += len(chunk)
                        elif isinstance(chunk, ModelUsage):
                            await record("memory_usage", chunk.tokens)
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
                result = (await service.commit_job(state["scope"], job_id, snapshot, proposal)
                          if job_id is not None else await service.commit(
                              state["scope"], state["run_id"], snapshot, proposal))
                return {"snapshot": snapshot, "result": result}
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
