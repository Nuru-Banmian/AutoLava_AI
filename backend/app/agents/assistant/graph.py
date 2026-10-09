import asyncio
import json
import re
from datetime import date
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
from app.agents.tools.query_granularity import month_followup_range
from app.core.config import Settings


class ChatModel(Protocol):
    model_name: str

    def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str | ModelUsage, None]: ...

    def stream_plan(self, messages: list[dict], schemas: list[dict]) -> AsyncGenerator[str | ModelUsage | ToolCall, None]: ...


def explicit_dates(question):
    """Read unambiguous literal dates; leave relative/ambiguous intent to planning."""
    year = None
    selected = set()
    for match in re.finditer(r"(\d{4}-\d{2}-\d{2})|(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", question):
        try:
            if match[1]:
                value = date.fromisoformat(match[1])
                year = value.year
            else:
                year = int(match[2]) if match[2] else year
                if year is None:
                    continue
                value = date(year, int(match[3]), int(match[4]))
            selected.add(value.isoformat())
        except ValueError:
            continue
    return selected


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
        # Short-term recall is a recent slice, separate from durable memories
        # and the paginated conversation kept for the user's history view.
        for message in reversed(conversation.messages[-10:]):
            candidate = {"role": message.role, "content": message.content}
            if message.charts and message.role == "assistant":
                # Retain referent metadata, without replaying old numeric prose
                # as assistant instructions or evidence for a new data answer.
                descriptions = [{key: chart.model_dump(mode="json")[key]
                                 for key in ("type", "title", "range", "unit")}
                                for chart in message.charts]
                candidate["content"] = "此前图表范围（仅识别追问，数值须重新查询）：" + json.dumps(
                    descriptions, ensure_ascii=False)
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
        if memory_index and retrieval["status"] != "available":
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
        chart_failures = []
        chart_required = chart_attempted = chart_prepared = False
        chart_repairs = 0
        requested_dates = set()
        queried_dates = set()
        date_repairs = 0
        comparison_required = comparison_obtained = False
        comparison_repairs = 0
        partial_repairs = 0
        deferred_text = False

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
                             "明细结论仅涵盖已返回行，完整统计以工具注明的全部匹配口径为准。")
            if any(t.get("error") == "context_capacity" for t in result_progress.values()):
                parts.append("context_capacity：本轮容量不足，已读证据保留，需要更多明细请缩小日期范围重新查询。")
            if query_failures:
                reasons = "、".join(sorted(set(query_failures.values())))
                parts.append(f"有{len(query_failures)}个查询目标未完成，原因：{reasons}。")
            if capacity_requests:
                parts.append(f"有{len(capacity_requests)}个查询请求未完成，原因：context_capacity。"
                             "此前已成功读取的结果保留。")
            if chart_failures:
                parts.append("有图表请求未生成，原因：" + "、".join(sorted(set(chart_failures)))
                             + "。仅随已完成回答保存成功准备的图表。")
            return "本轮查询仅部分完成：" + "".join(parts) if parts else ""

        async def response(input_messages, schemas, *, planning=False):
            nonlocal attempts, output_size, deferred_text
            deferred_text = False
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
                                    if (not planning and not (requested_dates - queried_dates)
                                            and (not comparison_required or comparison_obtained)
                                            and (not chart_required or chart_prepared)
                                            and (plan.kind not in ("query", "business", "saved_chart") or evidence)):
                                        require_evidence(plan, evidence, state["scope"], state["run_id"],
                                                         state["generation"])
                                        if partial_completion():
                                            # Validate completeness claims before publishing prose
                                            # when receipts still contain unread rows or failures.
                                            deferred_text = True
                                        else:
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
            nonlocal tool_count, query_started, chart_attempted, chart_prepared, comparison_obtained
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
                question=state["messages"][-1]["content"],
            )
            result = await tools.execute(call, storage, context)
            if call.name == "store_chart":
                chart_attempted = True
                chart_prepared = chart_prepared or result.get("status") == "prepared"
            if call.name == "store_query":
                for target in result.get("targets", []):
                    if target.get("comparison", {}).get("changes"):
                        comparison_obtained = True
                    period = target.get("requested_range") or target.get("range")
                    if target.get("status") not in ("complete", "partial", "unavailable") or not period:
                        continue
                    date_filters = [f for f in target.get("query_description", {}).get("filters", [])
                                    if f["field"] == "date"]
                    for selected in requested_dates:
                        if not period["start"] <= selected <= period["end"]:
                            continue
                        if any((f["op"] == "eq" and selected != f.get("value"))
                               or (f["op"] == "in" and selected not in f.get("value", []))
                               or (f["op"] == "gte" and selected < f.get("value", ""))
                               or (f["op"] == "lte" and selected > f.get("value", ""))
                               for f in date_filters):
                            continue
                        queried_dates.add(selected)
            if call.name == "store_chart" and result.get("error"):
                chart_failures.append(result["error"])
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
                **({"error_code": result["error"], "message": result.get("message", "图表请求未获执行。")}
                   if call.name == "store_chart" and "error" in result else {}),
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
                             "明细按read_ranges核对已返回行；仍有未返回内容时，"
                             "须说明本轮部分完成、已读/总行数及未读范围，不声称明细完整。"
                             "context_capacity只表示本轮容量不足，保留已成功结果并解释未读部分。"}

        def remind_grounding():
            messages.append(grounding_message())

        def trim_query_history():
            if plan.kind not in ("business", "query", "saved_chart") or query_started or not history_messages:
                return
            old_ids = {id(message) for message in history_messages}
            minimum = [message for message in messages if id(message) not in old_ids]
            following = grounding_message()
            page_room = min(12000, max(0, settings.agent_context_chars
                                      - context_size([*minimum, following]) - 2000 - 1000))
            # Reserve the largest bounded result the protected context supports,
            # along with answer/control room, before the first business read.
            # Skill/catalog receipts remain in messages and reduce this room.
            while (history_messages and context_size([*messages, following])
                   + page_room + 2000 + 1000 > settings.agent_context_chars):
                expired = history_messages.pop(0)
                messages[:] = [message for message in messages if message is not expired]

        async def complete_answer():
            nonlocal output_size
            require_evidence(plan, evidence, state["scope"], state["run_id"], state["generation"])
            if plan.kind == "query":
                notice = "\n\n本轮结果来自最新数据（本轮重新查询）。"
                if output_size + len(notice) > settings.agent_output_chars:
                    raise ModelFailure("output_budget")
                output_size += len(notice)
                await storage.record(state["scope"], state["run_id"], "delta", {"text": notice})
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
        question = state["messages"][-1]["content"]
        background = json.loads(state["messages"][-3]["content"])["store_background"]
        followup_range = month_followup_range(question, date.fromisoformat(background["local_date"]))
        previous_answer = next((item for item in reversed(history_messages) if item["role"] == "assistant"), None)
        chart_followup = bool(followup_range and previous_answer
                              and previous_answer["content"].startswith("此前图表范围（仅识别追问，数值须重新查询）："))
        # Compatibility with stale provider plans never permits historical evidence.
        if plan.kind == "saved_chart" or chart_followup:
            plan = plan.model_copy(update={"kind": "query"})
        if chart_followup:
            messages.insert(-1, {"role": "system", "content":
                "本轮是上一张图的月份追问，继承该图指标、分组和图型，重新查询并生成新图。"
                "按门店当地今天解析，本轮日期范围为" + json.dumps(followup_range, ensure_ascii=False)
                + "；使用此显式range，不沿用旧月份或旧数值。必须取得本轮store_chart的prepared后说明生成。"})
        if plan.kind == "query":
            messages.insert(-1, {"role": "system", "content":
                "图表追问也必须重新查询数据。沿用近期日期、指标和分组；必要信息不足先追问，"
                "说明结果来自最新数据，需要时生成新图，旧图保留查看。"
                "一般查询先汇总：月收入一次查询整月，年收入一次查询全年总结；"
                "周查询一次查询一周并按天分组，不逐日调用。用户细问再按月、日或分类拆分；"
                "明确要求明细、趋势图、分类或比较时遵从用户粒度。月份结算不能重复计入每天。"})
        requested_dates = explicit_dates(question) if plan.kind == "query" else set()
        comparison_required = (plan.kind == "query"
                               and bool(re.search(r"差额|变化率|环比|同比", question)))
        chart_required = (plan.kind == "query"
                          and (chart_followup or bool(re.search(r"(?:用|画|绘制|生成|重做).{0,160}(?:图|趋势)|"
                                                               r"图表|折线图|柱状图|条形图|趋势图|\bchart\b", question, re.I)))
                          and not re.search(r"(?:不用|不要|不需要|不)(?:再)?(?:画|生成|绘制)?(?:新)?"
                                            r"(?:折线|分组柱状|堆叠柱状|柱状|条形|趋势)?图", question))
        await storage.record(state["scope"], state["run_id"], "plan", {
            "kind": plan.kind, "queries": [q.model_dump(mode="json") for q in plan.queries],
        })
        if attempts >= settings.agent_max_steps:
            raise ModelFailure("step_budget")
        if plan.kind in ("business", "query", "saved_chart"):
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
            # Error receipts (including invalid arguments) can consume the
            # control reserve. Preserve evidence and the answer reserve rather
            # than issuing another model request with too little space.
            if (evidence and partial_completion()
                    and context_size(messages) > settings.agent_context_chars - 2000):
                return await complete_answer()
            calls, text = await response(messages, tools.schemas if hasattr(model, "stream_tools") else [])
            if not calls:
                if not text:
                    raise ModelFailure("model_format")
                if missing := requested_dates - queried_dates:
                    if date_repairs == 0:
                        date_repairs += 1
                        messages.append({"role": "system", "content":
                            "用户明确要求的日期尚未取得查询回执：" + "、".join(sorted(missing))
                            + "。dates是已有记录覆盖，不是查询限制；请用store_query的range查询这些日期。"
                            "无匹配记录才能说明未录入；未统计已有状态记录，只是金额未知。"})
                        continue
                    raise ModelFailure("grounding_unavailable")
                if comparison_required and not comparison_obtained:
                    if comparison_repairs == 0:
                        comparison_repairs += 1
                        messages.append({"role": "system", "content":
                            "本轮尚未取得后端差额/变化率。请用store_query一个目标的range和compare取得"
                            "comparison.changes，再引用difference/change_percent回答；两次独立汇总不能替代compare。"})
                        continue
                    raise ModelFailure("grounding_unavailable")
                if chart_required and not chart_prepared:
                    # Query evidence cannot substantiate a chart success claim.
                    # Keep speculative prose out of SSE, then give the provider
                    # one bounded opportunity to perform the missing operation.
                    if not chart_attempted and chart_repairs == 0:
                        chart_repairs += 1
                        messages.append({"role": "system", "content":
                            "用户明确要求画图，本轮尚无store_chart的prepared回执。"
                            "请用当前result_ref调用store_chart；图表参数依技能/schema。"
                            "取得prepared后再回答，不能仅用文字声称已生成。"})
                        continue
                    if not chart_attempted or not chart_failures:
                        raise ModelFailure("grounding_unavailable")
                    return await complete_answer()
                if deferred_text:
                    if re.search(r"(?:已读取|已读|读取已完成).{0,16}(?:全部|所有)|"
                                 r"(?:已全部|已完整).{0,8}(?:读取|读完)|无遗漏|无未读", text):
                        if partial_repairs == 0:
                            partial_repairs += 1
                            messages.append({"role": "system", "content":
                                partial_completion() + "请按真实回执修正回答，不宣称明细全部读完。"
                                "图表完整点数与模型已读明细分别说明；更多明细须缩小日期范围新查，不支持续页。"})
                            continue
                        raise ModelFailure("grounding_unavailable")
                    await storage.record(state["scope"], state["run_id"], "delta", {"text": text})
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
