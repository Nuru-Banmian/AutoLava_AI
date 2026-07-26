from collections.abc import Sequence
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.contracts import (
    EvidenceBundle,
    EvidencePlan,
    ModelMessage,
    TurnPlan,
    TurnResult,
    TurnRoute,
)
from app.agent.model import ModelAdapter

SAFE_FAILURE_MESSAGE = "模型服务暂时不可用，请稍后重试。"
MAX_MODEL_CALLS = 2
MAX_EVIDENCE_CALLS = 1


class EvidenceCollector(Protocol):
    async def collect(self, plan: EvidencePlan) -> EvidenceBundle: ...


class TurnState(TypedDict):
    messages: Sequence[ModelMessage]
    plan: TurnPlan | None
    evidence: EvidenceBundle | None
    result: TurnResult | None
    model_calls: int
    evidence_calls: int


class AgentTurnWorkflow:
    """A fixed one-turn graph with no loop, interrupt, or checkpoint."""

    def __init__(self, *, model: ModelAdapter, evidence_collector: EvidenceCollector) -> None:
        self.model = model
        self.evidence_collector = evidence_collector
        graph = StateGraph(TurnState)
        graph.add_node("plan", self._plan)
        graph.add_node("finish_plan", self._finish_plan)
        graph.add_node("collect_evidence", self._collect_evidence)
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
            {"answer": "answer", "finish": "finish_plan"},
        )
        graph.add_edge("finish_plan", END)
        graph.add_edge("answer", END)
        self._graph = graph.compile()

    async def run(self, messages: Sequence[ModelMessage]) -> TurnResult:
        state: TurnState = {
            "messages": messages,
            "plan": None,
            "evidence": None,
            "result": None,
            "model_calls": 0,
            "evidence_calls": 0,
        }
        final = await self._graph.ainvoke(state)
        result = final["result"]
        if result is None:
            return _safe_failure()
        return result

    async def _plan(self, state: TurnState) -> dict:
        if state["model_calls"] >= MAX_MODEL_CALLS:
            return {"plan": _safe_failure_plan(), "model_calls": state["model_calls"]}
        try:
            plan = await self.model.plan_turn(state["messages"])
        except Exception:
            plan = _safe_failure_plan()
        return {"plan": plan, "model_calls": state["model_calls"] + 1}

    @staticmethod
    def _route_plan(state: TurnState) -> str:
        plan = state["plan"]
        return "collect" if plan is not None and plan.route == TurnRoute.EVIDENCE else "finish"

    @staticmethod
    async def _finish_plan(state: TurnState) -> dict:
        plan = state["plan"]
        if plan is None or plan.route == TurnRoute.SAFE_FAILURE:
            return {"result": _safe_failure()}
        if plan.route == TurnRoute.CLARIFY:
            return {"result": TurnResult(route="clarify", content=plan.question or "")}
        if plan.route == TurnRoute.DIRECT_ANSWER:
            return {"result": TurnResult(route="answer", content=plan.answer or "")}
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
        try:
            evidence = await self.evidence_collector.collect(plan.evidence_plan)
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
        return "answer" if state["evidence"] is not None and state["result"] is None else "finish"

    async def _answer(self, state: TurnState) -> dict:
        if state["model_calls"] >= MAX_MODEL_CALLS or state["evidence"] is None:
            return {"result": _safe_failure()}
        try:
            answer = await self.model.answer_turn(state["messages"], state["evidence"])
        except Exception:
            return {
                "result": _safe_failure(),
                "model_calls": state["model_calls"] + 1,
            }
        return {
            "result": TurnResult(route="answer", content=answer),
            "model_calls": state["model_calls"] + 1,
        }


def _safe_failure_plan() -> TurnPlan:
    return TurnPlan(route="safe_failure", message=SAFE_FAILURE_MESSAGE)


def _safe_failure() -> TurnResult:
    return TurnResult(route="safe_failure", content=SAFE_FAILURE_MESSAGE)
