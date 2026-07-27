from collections.abc import Callable, Sequence
from datetime import datetime
import re
from typing import Protocol, TypedDict
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph

from app.agent.business_evidence import EvidenceClarificationError
from app.agent.contracts import (
    CollectedEvidence,
    EvidenceBundle,
    EvidencePlan,
    ModelMessage,
    RevenueAnalysisEvidenceBundle,
    SettlementDetailsRequest,
    TurnPlan,
    TurnResult,
    TurnRoute,
    WorkflowResult,
)
from app.agent.model import ModelAdapter, ModelAttempt, RepairableModelPlanError
from app.agent.runtime import RuntimeContext

SAFE_FAILURE_MESSAGE = "模型服务暂时不可用，请稍后重试。"
OPEN_BUSINESS_RECORDS_MESSAGE = "可查看所选月份的营业记录。"
PLAN_REPAIR_FEEDBACK = (
    "The previous TurnPlan had a format, enum, or structural error. "
    "Return one corrected TurnPlan matching the schema. "
    "Do not add identity, store scope, timezone, SQL, schema, URL, or role fields."
)
MAX_MODEL_CALLS = 3
MAX_EVIDENCE_CALLS = 2
SETTLEMENT_DETAILS_REQUIRE_EXPLICIT_MESSAGE = (
    "请明确询问结算公司、开票记录、待到账、已确认金额或某个公司的结算金额。"
)
EXPLICIT_PERCENTAGE_TERMS = (
    "%",
    "百分比",
    "百分之",
    "变化率",
    "增长率",
    "下降率",
    "环比",
    "同比",
    "涨幅",
    "跌幅",
    "增幅",
    "降幅",
)
NEGATED_PERCENTAGE_TERMS = (
    "不要百分",
    "不用百分",
    "不需要百分",
    "无需百分",
    "别算百分",
    "不要算百分",
    "不要%",
    "不用%",
    "只给金额",
    "只看金额",
    "仅给金额",
    "仅看金额",
)
NAVIGATION_TARGET = re.compile(
    r"(?:https?://|www\.|/api/|/database(?:[/?#\s]|$))",
    re.IGNORECASE,
)
DIRECT_ANSWER_BUSINESS_CLAIM = re.compile(
    r"(?:\d+(?:[.,]\d+)?\s*(?:欧元|元|辆车|辆|个经营日|天|%|％))"
    r"|(?:\d{4}[-年]\d{1,2}(?:[-月]\d{1,2}日?)?)"
    r"|(?:(?:已经|已|将|为你)?(?:打开|跳转|前往|访问).{0,20}"
    r"(?:营业记录|每日台账|页面))"
    r"|(?:导致|造成|归因于|原因是|主要来自)"
)
SAFE_DIRECT_ANSWER_QUESTION = re.compile(
    r"^\s*(?:"
    r"(?:请|麻烦)?(?:介绍|说明)(?:一下)?"
    r"(?:你|agent|智能助手|助手)?(?:的)?(?:能力|功能|能力范围|功能范围)"
    r"|(?:你|agent|智能助手|助手)?(?:能|可以|能够)"
    r"(?:帮我)?(?:做|回答|处理|支持)(?:什么|哪些(?:事情|问题|功能)?)"
    r"|(?:怎么|如何)(?:使用|用)(?:你|agent|智能助手|助手)"
    r")\s*[?？。！!]*\s*$",
    re.IGNORECASE,
)
SAFE_DIRECT_ANSWER_PREFIX = re.compile(
    r"^\s*(?:(?:我|本(?:agent|智能助手|助手))\s*)?"
    r"(?:可以|能|能够|支持|无法|不能)",
    re.IGNORECASE,
)


class EvidenceCollector(Protocol):
    async def collect(
        self,
        plan: EvidencePlan,
        context: RuntimeContext,
    ) -> CollectedEvidence: ...


class TurnState(TypedDict):
    messages: Sequence[ModelMessage]
    context: RuntimeContext
    plan: TurnPlan | None
    evidence: CollectedEvidence | None
    result: TurnResult | None
    model_calls: int
    evidence_calls: int
    attempts: list[ModelAttempt]


class AgentTurnWorkflow:
    """A fixed one-turn graph with no loop, interrupt, or checkpoint."""

    def __init__(self, *, model: ModelAdapter, evidence_collector: EvidenceCollector) -> None:
        self.model = model
        self.evidence_collector = evidence_collector
        graph = StateGraph(TurnState)
        graph.add_node("plan", self._plan)
        graph.add_node("finish_plan", self._finish_plan)
        graph.add_node("collect_evidence", self._collect_evidence)
        graph.add_node("collect_supplemental_evidence", self._collect_supplemental_evidence)
        graph.add_node("answer", self._answer)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges(
            "plan",
            self._route_plan,
            {"collect": "collect_evidence", "finish": "finish_plan"},
        )
        graph.add_conditional_edges(
            "collect_evidence",
            self._route_collected_evidence,
            {
                "supplement": "collect_supplemental_evidence",
                "answer": "answer",
                "finish": "finish_plan",
            },
        )
        graph.add_edge("collect_supplemental_evidence", "answer")
        graph.add_edge("finish_plan", END)
        graph.add_edge("answer", END)
        self._graph = graph.compile()

    async def run(
        self,
        messages: Sequence[ModelMessage],
        context: RuntimeContext,
        *,
        observer: Callable[[ModelAttempt], None] | None = None,
    ) -> WorkflowResult:
        state: TurnState = {
            "messages": messages,
            "context": context,
            "plan": None,
            "evidence": None,
            "result": None,
            "model_calls": 0,
            "evidence_calls": 0,
            "attempts": [],
        }
        final = await self._graph.ainvoke(state)
        attempts = final["attempts"]
        if observer is not None:
            for attempt in attempts:
                observer(attempt)
        result = final["result"]
        if result is None:
            return WorkflowResult(turn=_safe_failure())
        recovery_status = (
            "fallback"
            if any(attempt.is_fallback for attempt in attempts)
            else "retried"
            if len(attempts) > 1
            and any(attempt.result == "failure" for attempt in attempts)
            else "none"
        )
        return WorkflowResult(
            turn=result.model_copy(update={"recovery_status": recovery_status}),
            evidence=final["evidence"],
        )

    async def _plan(self, state: TurnState) -> dict:
        if state["model_calls"] >= MAX_MODEL_CALLS:
            return {"plan": _safe_failure_plan(), "model_calls": state["model_calls"]}
        try:
            plan = await self.model.plan_turn(
                state["messages"], observer=state["attempts"].append
            )
            calls = state["model_calls"] + 1
        except RepairableModelPlanError:
            calls = state["model_calls"] + 1
            if calls >= MAX_MODEL_CALLS:
                return {"plan": _safe_failure_plan(), "model_calls": calls}
            try:
                plan = await self.model.plan_turn(
                    [
                        *state["messages"],
                        ModelMessage(role="system", content=PLAN_REPAIR_FEEDBACK),
                    ],
                    observer=state["attempts"].append,
                )
            except Exception:
                plan = _safe_failure_plan()
            calls += 1
        except Exception:
            plan = _safe_failure_plan()
            calls = state["model_calls"] + 1
        return {"plan": plan, "model_calls": calls}

    @staticmethod
    def _route_plan(state: TurnState) -> str:
        plan = state["plan"]
        return "collect" if plan is not None and plan.route == TurnRoute.EVIDENCE else "finish"

    @staticmethod
    async def _finish_plan(state: TurnState) -> dict:
        if state["result"] is not None:
            return {}
        plan = state["plan"]
        if plan is None or plan.route == TurnRoute.SAFE_FAILURE:
            return {"result": _safe_failure()}
        if plan.route == TurnRoute.CLARIFY:
            return {"result": TurnResult(route="clarify", content=plan.question or "")}
        if plan.route == TurnRoute.DIRECT_ANSWER:
            answer = plan.answer or ""
            if not _is_safe_direct_answer(state["messages"], answer):
                return {"result": _safe_failure()}
            return {"result": TurnResult(route="answer", content=answer)}
        if plan.route == TurnRoute.ACTION and plan.action is not None:
            current_month = datetime.now(
                ZoneInfo(state["context"].store_timezone)
            ).strftime("%Y-%m")
            if plan.action.end_month > current_month:
                return {"result": _safe_failure()}
            return {
                "result": TurnResult(
                    route="answer",
                    content=OPEN_BUSINESS_RECORDS_MESSAGE,
                    action=plan.action,
                )
            }
        return {"result": _safe_failure()}

    async def _collect_evidence(self, state: TurnState) -> dict:
        plan = state["plan"]
        if (
            plan is None
            or plan.evidence_plan is None
            or state["evidence_calls"] >= MAX_EVIDENCE_CALLS
        ):
            return {
                "result": _safe_failure(),
                "evidence_calls": state["evidence_calls"],
            }
        if not _evidence_request_is_explicit(
            plan.evidence_plan,
            state["messages"],
        ):
            return {
                "result": TurnResult(
                    route="clarify",
                    content=SETTLEMENT_DETAILS_REQUIRE_EXPLICIT_MESSAGE,
                ),
                "evidence_calls": state["evidence_calls"],
            }
        try:
            evidence_plan = _enforce_explicit_percentage_request(
                plan.evidence_plan,
                state["messages"],
            )
            evidence = await self.evidence_collector.collect(
                evidence_plan,
                state["context"],
            )
        except EvidenceClarificationError as error:
            return {
                "result": TurnResult(route="clarify", content=str(error)),
                "evidence_calls": state["evidence_calls"] + 1,
            }
        except Exception:
            return {
                "result": _safe_failure(),
                "evidence_calls": state["evidence_calls"] + 1,
            }
        return {
            "evidence": evidence,
            "evidence_calls": state["evidence_calls"] + 1,
        }

    @staticmethod
    def _route_collected_evidence(state: TurnState) -> str:
        evidence = state["evidence"]
        plan = state["plan"]
        if evidence is None or state["result"] is not None:
            return "finish"
        if (
            isinstance(evidence, RevenueAnalysisEvidenceBundle)
            and evidence.findings.unexplained_amount != 0
            and plan is not None
            and plan.supplemental_evidence_plan is not None
            and state["evidence_calls"] < MAX_EVIDENCE_CALLS
        ):
            return "supplement"
        return "answer"

    async def _collect_supplemental_evidence(self, state: TurnState) -> dict:
        plan = state["plan"]
        primary = state["evidence"]
        if (
            plan is None
            or plan.supplemental_evidence_plan is None
            or not isinstance(primary, RevenueAnalysisEvidenceBundle)
            or primary.findings.unexplained_amount == 0
            or state["evidence_calls"] >= MAX_EVIDENCE_CALLS
        ):
            return {}
        try:
            supplemental_plan = _enforce_explicit_percentage_request(
                plan.supplemental_evidence_plan,
                state["messages"],
            )
            supplemental = await self.evidence_collector.collect(
                supplemental_plan,
                state["context"],
            )
            if not isinstance(supplemental, EvidenceBundle):
                raise ValueError("supplemental evidence must be a business metric")
        except Exception:
            return {"evidence_calls": state["evidence_calls"] + 1}
        return {
            "evidence": primary.model_copy(
                update={
                    "supplemental_evidence": supplemental,
                    "summary": (
                        f"{primary.summary}补充证据：{supplemental.summary}"
                        "该补充证据仅用于缩小尚未解释范围，不构成因果结论。"
                    ),
                }
            ),
            "evidence_calls": state["evidence_calls"] + 1,
        }

    async def _answer(self, state: TurnState) -> dict:
        if state["model_calls"] >= MAX_MODEL_CALLS or state["evidence"] is None:
            return {"result": _safe_failure()}
        try:
            answer = await self.model.answer_turn(
                state["messages"],
                state["evidence"],
                observer=state["attempts"].append,
            )
        except Exception:
            return {
                "result": _safe_failure(),
                "model_calls": state["model_calls"] + 1,
            }
        return {
            "result": TurnResult(
                route="answer",
                content=_validated_readable_answer(answer, state["evidence"]),
            ),
            "model_calls": state["model_calls"] + 1,
        }


def _safe_failure_plan() -> TurnPlan:
    return TurnPlan(route="safe_failure", message=SAFE_FAILURE_MESSAGE)


def _safe_failure() -> TurnResult:
    return TurnResult(route="safe_failure", content=SAFE_FAILURE_MESSAGE)


def _is_safe_direct_answer(
    messages: Sequence[ModelMessage],
    answer: str,
) -> bool:
    question = next(
        (message.content for message in reversed(messages) if message.role == "user"),
        "",
    )
    return bool(
        SAFE_DIRECT_ANSWER_QUESTION.fullmatch(question)
        and SAFE_DIRECT_ANSWER_PREFIX.match(answer)
        and not NAVIGATION_TARGET.search(answer)
        and not DIRECT_ANSWER_BUSINESS_CLAIM.search(answer)
    )


def _validated_readable_answer(answer: str, evidence: CollectedEvidence) -> str:
    return answer if answer.strip() == evidence.summary else evidence.summary


def _evidence_request_is_explicit(
    plan: EvidencePlan,
    messages: Sequence[ModelMessage],
) -> bool:
    request = plan.requests[0]
    if not isinstance(request, SettlementDetailsRequest):
        return True
    question = next(
        (
            message.content.casefold()
            for message in reversed(messages)
            if message.role == "user"
        ),
        "",
    )
    explicit_terms = (
        "公司结算",
        "结算公司",
        "开票记录",
        "开票",
        "待到账",
        "已确认",
        "到账",
    )
    if any(term in question for term in explicit_terms):
        return True
    return (
        request.company_name is not None
        and request.company_name.casefold() in question
        and any(term in question for term in ("金额", "多少", "收入", "结算"))
    )


def _enforce_explicit_percentage_request(
    plan: EvidencePlan,
    messages: Sequence[ModelMessage],
) -> EvidencePlan:
    request = plan.requests[0]
    comparison = getattr(request, "comparison", None)
    includes_percentage = bool(
        getattr(request, "include_percentage", False)
        or (comparison is not None and comparison.include_percentage)
    )
    if not includes_percentage:
        return plan
    user_message = next(
        (message.content for message in reversed(messages) if message.role == "user"),
        "",
    )
    percentage_is_negated = any(
        term in user_message for term in NEGATED_PERCENTAGE_TERMS
    )
    if not percentage_is_negated and any(
        term in user_message for term in EXPLICIT_PERCENTAGE_TERMS
    ):
        return plan
    if hasattr(request, "include_percentage"):
        return plan.model_copy(
            update={
                "requests": [
                    request.model_copy(update={"include_percentage": False}),
                ]
            }
        )
    return plan.model_copy(
        update={
            "requests": [
                request.model_copy(
                    update={
                        "comparison": comparison.model_copy(
                            update={"include_percentage": False}
                        )
                    }
                )
            ]
        }
    )
