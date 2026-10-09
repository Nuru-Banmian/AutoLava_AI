import asyncio
import json
from importlib.resources import files
from typing import Protocol
from collections.abc import AsyncGenerator
from contextlib import aclosing
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agents.assistant.state import AssistantState
from app.agents.assistant.grounding import (
    PLAN_PROMPT, PLAN_SCHEMA, TurnEvidence, parse_plan, require_evidence,
)
from app.agents.providers.bailian import ModelFailure, ModelUsage, ToolCall
from app.agents.registry import capabilities
from app.agents.runtime.repository import ChatRepository
from app.agents.tools.context import ToolContext
from app.core.config import Settings


class ChatModel(Protocol):
    model_name: str

    def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str | ModelUsage, None]: ...

    def stream_plan(self, messages: list[dict], schemas: list[dict]) -> AsyncGenerator[str | ModelUsage | ToolCall, None]: ...


def create_graph(model: ChatModel, storage: ChatRepository, settings: Settings,
                 *, agent_capabilities=None, memory_index=None):
    prompt = files("app.agents.assistant").joinpath("prompts.md").read_text(encoding="utf-8")
    skills, tools = capabilities() if agent_capabilities is None else agent_capabilities
    catalog = json.dumps({"enabled_skills": list(skills.metadata.values())}, ensure_ascii=False)

    def context_size(messages, schemas=None):
        return len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(
            (tools.schemas if hasattr(model, "stream_tools") else [])
            if schemas is None else schemas, ensure_ascii=False))

    def plan_messages(messages):
        # Planning needs scope/history, not the full answer-writing instructions.
        return [{"role": "system", "content": PLAN_PROMPT}, *messages[1:]]

    def turn_context_size(messages):
        return max(context_size([*messages, {"role": "system", "content":
                    "本轮为通用问答或背景讨论，不把历史统计当作当前经营事实。"}]),
                   context_size(plan_messages(messages), PLAN_SCHEMA))

    async def context(state: AssistantState):
        retrieval = (await memory_index.retrieve(state["scope"], state["run_id"])
                     if memory_index else {"status": "unavailable", "items": []})
        background = await storage.background(state["scope"], state["run_id"])
        background["memories"] = retrieval["items"]
        background["memory_retrieval"] = retrieval["status"]
        conversation = await storage.conversation(state["scope"])
        data = json.dumps({"store_background": background}, ensure_ascii=False)
        base = [{"role": "system", "content": prompt},
                {"role": "system", "content": catalog}, {"role": "user", "content": data},
                {"role": "system", "content":
                 "store_background为当前快照；经营数据须本轮读技能并查询，不复述历史数字。"
                 "洗车数量关闭仅表示本轮不使用，不表示缺乏数据。"
                 "本轮后台记忆整理尚未执行，不确认保存、合并或索引，不复述历史操作回执。"}]
        messages = []
        for message in reversed(conversation.messages):
            candidate = {"role": message.role, "content": message.content}
            if turn_context_size([*base, candidate, *reversed(messages)]) > settings.agent_context_chars:
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
        chronological = list(reversed(messages))
        return {"messages": [*base[:2], *chronological[:-1], *base[2:], *chronological[-1:]],
                "generation": conversation.generation}

    async def generate(state: AssistantState):
        results = storage.temporary_results.for_run(state["scope"], state["run_id"], state["generation"])
        try:
            return await generate_with_results(state, results)
        finally:
            storage.temporary_results.release(state["run_id"])

    async def generate_with_results(state: AssistantState, results):
        output_size = len((await storage.run(state["scope"], state["run_id"])).output)
        attempts = tool_count = 0
        messages = list(state["messages"])
        # context() places prior conversation between the initial system/catalog
        # and the protected background, control message and current question.
        history_messages = list(messages[2:-3])
        evidence = []
        result_progress = {}
        query_failures = {}
        capacity_requests = set()
        query_started = False

        def partial_completion():
            selected = read = 0
            for target in result_progress.values():
                count = target.get("row_count", target["selected_count"])
                ranges = target.get("read_ranges") or [target.get("read_range", {"start": 0, "end": 0})]
                obtained = sum(max(0, min(count, item["end"]) - max(1, item["start"]) + 1)
                               for item in ranges)
                selected += count
                read += min(count, obtained)
            parts = []
            if read < selected:
                parts.append(f"已读取 {read}/{selected} 行，仍有 {selected - read} 行未读取。"
                             "明细结论仅涵盖已读页，完整统计以工具注明的全部匹配口径为准。")
            if query_failures:
                reasons = "、".join(sorted(set(query_failures.values())))
                parts.append(f"有{len(query_failures)}个查询目标未完成，原因：{reasons}。")
            if capacity_requests:
                parts.append(f"有{len(capacity_requests)}个查询请求未完成，原因：context_capacity。"
                             "此前已成功读取的结果保留。")
            return "本轮查询仅部分完成：" + "".join(parts) if parts else ""

        async def response(input_messages, schemas, *, planning=False):
            nonlocal attempts, output_size
            calls, text = [], ""
            for retry in range(settings.agent_max_calls):
                if attempts >= settings.agent_max_steps:
                    raise ModelFailure("step_budget")
                if context_size(input_messages, schemas) > settings.agent_context_chars:
                    raise ModelFailure("context_budget")
                attempts += 1
                await storage.record(state["scope"], state["run_id"], "attempt", {"number": attempts})
                try:
                    if planning and hasattr(model, "stream_plan"):
                        stream = model.stream_plan(input_messages, schemas)
                    elif hasattr(model, "stream_tools"):
                        stream = model.stream_tools(input_messages, schemas)
                    else:
                        stream = model.stream(input_messages)
                    async with aclosing(stream) as chunks:
                        async for chunk in chunks:
                            if isinstance(chunk, ModelUsage):
                                await storage.record(state["scope"], state["run_id"], "usage", chunk.tokens)
                            elif isinstance(chunk, ToolCall):
                                if len(calls) >= settings.agent_max_tool_calls or any(c.id == chunk.id for c in calls):
                                    raise ModelFailure("model_format")
                                calls.append(chunk)
                                output_size += len(chunk.arguments)
                                if output_size > settings.agent_output_chars:
                                    raise ModelFailure("output_budget")
                            elif isinstance(chunk, str):
                                output_size += len(chunk)
                                notice = partial_completion() if not planning else ""
                                reserved = len(notice) + 2 if notice else 0
                                if output_size + reserved > settings.agent_output_chars:
                                    raise ModelFailure("output_budget")
                                if chunk:
                                    text += chunk
                                    if not planning:
                                        require_evidence(plan, evidence, state["scope"], state["run_id"],
                                                         state["generation"])
                                        await storage.record(state["scope"], state["run_id"], "delta", {"text": chunk})
                            else:
                                raise ModelFailure("model_format")
                    break
                except ModelFailure as exc:
                    if text or calls or not exc.retryable or retry + 1 == settings.agent_max_calls:
                        raise
                    await asyncio.sleep(0.25 * (retry + 1))
            return calls, text

        async def execute(call):
            nonlocal tool_count, query_started
            tool_count += 1
            if tool_count > settings.agent_max_tool_calls:
                raise ModelFailure("tool_budget")
            trim_query_history()
            if call.name in ("store_overview", "store_query", "store_chart"):
                query_started = True
            empty_result = {"role": "tool", "tool_call_id": call.id, "content": ""}
            following = [grounding_message()] if call.name in ("store_overview", "store_query") else []
            remaining_context = max(0, settings.agent_context_chars
                                    - context_size([*messages, empty_result, *following])
                                    - 2000 - 1000)
            context = ToolContext(
                scope=state["scope"], run_id=state["run_id"], generation=state["generation"],
                remaining_result_chars=min(12000, remaining_context),
                results=results, catalogs=storage.catalogs,
                remaining_context_chars=remaining_context,
            )
            result = await tools.execute(call, storage, context)
            context_capacity = result.get("error") == "context_capacity" or any(
                target.get("error") == "context_capacity" for target in result.get("targets", []))
            if call.name in ("store_query", "store_chart"):
                # A batch rejected before target execution has no target receipts.
                # Track the exact request until it produces individual receipts;
                # those receipts then carry any remaining target failures.
                if result.get("error") == "context_capacity" or result.get("targets"):
                    request_key = (call.name, json.dumps(json.loads(call.arguments), sort_keys=True))
                    if result.get("error") == "context_capacity":
                        capacity_requests.add(request_key)
                    else:
                        capacity_requests.discard(request_key)
                for target in result.get("targets", []):
                    if target.get("result_ref") and type(target.get("selected_count")) is int:
                        result_progress[target["result_ref"]] = target
                    if target.get("status") == "failed" and target.get("error"):
                        query_failures[target["id"]] = target["error"]
                    elif target.get("status") in ("complete", "partial", "unavailable"):
                        query_failures.pop(target["id"], None)
            if (call.name == "store_query" and plan.kind == "query"
                    and result.get("status") in ("complete", "partial")
                    and any(target.get("status") in ("complete", "unavailable")
                            or (target.get("status") == "partial" and target.get("result_ref"))
                            for target in result.get("targets", []))):
                # Only successful server results can ground business prose; errors remain receipts.
                evidence.append(TurnEvidence(state["scope"], state["run_id"], state["generation"],
                                             ("query", "query"), ("query", "query"), call.id))
            # Reauthorizes after execution; reset/stopped/revoked runs cannot publish.
            await storage.record(state["scope"], state["run_id"], "tool", {
                "name": call.name if call.name in tools.tools else "unauthorized",
                "status": ("denied" if "error" in result or result.get("status") == "failed" else
                           "partial" if result.get("status") == "partial" else "completed"),
                **({"message": result.get("message", "查询目标未全部完成，请查看回复中的逐项说明。"),
                    "error_code": result.get("error", "context_capacity" if context_capacity else "query_targets_failed")}
                   if call.name == "store_query" and ("error" in result or result.get("status") in ("partial", "failed")) else {}),
                **({"range": result["range"]} if "range" in result else {}),
                **({"error_code": result["error"], "message": (
                    "计算请求参数无效，请使用表达式参数。" if result["error"] == "invalid_tool_arguments"
                    else result.get("message", "计算请求未获执行。")
                )} if call.name == "calculate" and "error" in result else {}),
            })
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result, ensure_ascii=False)})
            if call.name == "store_query" and plan.kind == "query" and context_capacity and not evidence:
                # No successful snapshot exists to support even a partial answer;
                # do not make another over-capacity model call or invent evidence.
                raise ModelFailure("grounding_unavailable")
            return result

        def grounding_message():
            return {"role": "system", "content":
                             "请依据本轮工具结果组织回答，并核对本轮召回的篇幅偏好。"
                             "条数上限适用于整个回答（含数据清单），将必要口径合并到限定条目内。"
                             "若偏好为最多N点，整答只使用一个不超过N项的编号列表，"
                             "每项用一个连续段落，不另加标题、子列表、引言或结语。"
                             "先数据后结论可将数据与口径放在第一项，结论与建议放在最后一项。"
                             "台账合计不能证明具体商品收入来源或经营稳定。"
                             "评价正常、好坏或达标需要工具提供的历史、目标或比较基准；"
                             "只有期间汇总时，结论说明本期数值及评价依据不足，建议表述为待核对事项。"
                             "记录洗车数量关闭只说明本轮不使用指标，不说明没有历史记录、"
                             "没有发生洗车业务或行业本身不能计算该指标。"
                             "不可用原因只能采用工具明确给出的当前原因。"
                             "分页结果按最新read_ranges核对累计已读行；仍有未读内容时，"
                             "须说明本轮部分完成、已读/总行数及未读范围，不声称明细完整。"
                             "context_capacity只表示本轮容量不足，保留已成功结果并解释未读部分。"}

        def remind_grounding():
            messages.append(grounding_message())

        def trim_query_history():
            if plan.kind not in ("business", "query") or query_started or not history_messages:
                return
            old_ids = {id(message) for message in history_messages}
            minimum = [message for message in messages if id(message) not in old_ids]
            following = grounding_message()
            page_room = min(12000, max(0, settings.agent_context_chars
                                      - context_size([*minimum, following]) - 2000 - 1000))
            # Reserve the largest page that the protected context can support,
            # along with answer/control room, before the first business read.
            # Skill/catalog receipts remain in messages and reduce this room.
            while (history_messages and context_size([*messages, following])
                   + page_room + 2000 + 1000 > settings.agent_context_chars):
                expired = history_messages.pop(0)
                messages[:] = [message for message in messages if message is not expired]

        async def complete_answer():
            nonlocal output_size
            require_evidence(plan, evidence, state["scope"], state["run_id"], state["generation"])
            if note := partial_completion():
                notice = "\n\n" + note
                if output_size + len(notice) > settings.agent_output_chars:
                    raise ModelFailure("output_budget")
                output_size += len(notice)
                await storage.record(state["scope"], state["run_id"], "delta", {"text": notice})
            await storage.record(state["scope"], state["run_id"], "completed", {"status": "completed"})
            return {}

        calls, _ = await response(plan_messages(messages), PLAN_SCHEMA, planning=True)
        plan = parse_plan(calls)
        await storage.record(state["scope"], state["run_id"], "plan", {
            "kind": plan.kind, "queries": [q.model_dump(mode="json") for q in plan.queries],
        })
        if attempts >= settings.agent_max_steps:
            raise ModelFailure("step_budget")
        if plan.kind in ("business", "query"):
            if 1 + len(plan.queries) > settings.agent_max_tool_calls:
                raise ModelFailure("tool_budget")
            skill = ToolCall(uuid4().hex, "read_skill", '{"skill":"store-analysis"}')
            messages.append({"role": "assistant", "content": None, "tool_calls": [skill.wire()]})
            result = await execute(skill)
            if (result.get("skill") != "store-analysis" or not result.get("body")
                    or "error" in result):
                raise ModelFailure("grounding_unavailable")
            for query in plan.queries:
                call = ToolCall(uuid4().hex, "store_overview", query.model_dump_json())
                messages.append({"role": "assistant", "content": None, "tool_calls": [call.wire()]})
                result = await execute(call)
                item = TurnEvidence.from_result(state["scope"], state["run_id"], state["generation"],
                                                query, call.id, result)
                evidence.append(item)
                await storage.record(state["scope"], state["run_id"], "grounding", {
                    "run_id": item.run_id, "generation": item.generation,
                    "store_id": item.scope.store_id, "tool_call_id": item.tool_call_id,
                    "source": "AnalyticsService", "requested_range": query.model_dump(mode="json"),
                    "range": result["range"],
                })
            if plan.kind == "business":
                require_evidence(plan, evidence, state["scope"], state["run_id"], state["generation"])
                remind_grounding()
        else:
            # Make the accepted route explicit without replaying a control-tool conversation.
            messages.insert(-1, {"role": "system", "content": (
                "本轮须先澄清日期或意图，不陈述当前经营数值。" if plan.kind == "clarify"
                else "本轮为通用问答或背景讨论，不把历史统计当作当前经营事实。"
            )})

        while attempts < settings.agent_max_steps:
            trim_query_history()
            # Error receipts (including invalid continuations) can consume the
            # control reserve. Preserve evidence and the answer reserve rather
            # than issuing another model request with too little space.
            if (evidence and partial_completion()
                    and context_size(messages) > settings.agent_context_chars - 2000):
                return await complete_answer()
            calls, text = await response(messages, tools.schemas if hasattr(model, "stream_tools") else [])
            if not calls:
                if not text:
                    raise ModelFailure("model_format")
                return await complete_answer()
            messages.append({"role": "assistant", "content": text or None,
                             "tool_calls": [call.wire() for call in calls]})
            for call in calls:
                await execute(call)
            if any(call.name in ("store_overview", "store_query") for call in calls):
                remind_grounding()
        raise ModelFailure("step_budget")

    builder = StateGraph(AssistantState)
    builder.add_node("context", context)
    builder.add_node("generate", generate)
    builder.add_edge(START, "context")
    builder.add_edge("context", "generate")
    builder.add_edge("generate", END)
    return builder.compile()
