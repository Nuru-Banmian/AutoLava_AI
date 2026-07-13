# AutoLava AI Phase 3 Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a permission-safe AI assistant for store-scoped queries, qualitative analysis, ledger drafts, and explicit approval-gated ledger mutations with complete conversation history and audit evidence.

**Architecture:** Treat the language model as an untrusted planner: it emits typed intents and proposal payloads, while backend services perform authorization, category resolution, date validation, revenue calculation, and all writes. A LangGraph workflow routes read operations directly to permission-scoped domain tools and routes writes into persisted, expiring proposals; a separate confirmation endpoint executes a proposal once. Provider selection is isolated behind an interface so DeepSeek and Qwen failures do not leak into business services.

**Tech Stack:** Existing Phase 1/2 stack plus LangChain, LangGraph, OpenAI-compatible DeepSeek/Qwen clients, Pydantic structured output, React chat UI, pytest fakes, Vitest, and Playwright.

## Global Constraints

- Phases 1 and 2 are complete; Phase 3 does not mutate workforce or payroll data.
- DeepSeek-V3 handles normal conversation, DeepSeek-R1 handles complex reasoning, and Qwen-Plus is the fallback when DeepSeek is unavailable.
- The model never receives database credentials, never emits executable SQL, and never bypasses backend authorization or validation.
- Read-only answers may return immediately; create, update, and delete operations require a persisted preview plus explicit confirmation.
- Every mutation targets only the conversation's currently selected store, including for administrators.
- A regular user may query/analyze only assigned stores; an administrator may request cross-store analysis but not cross-store mutation.
- The assistant cannot set `daily_revenue`; it may set category amounts and the ledger service recomputes the total.
- A draft with unresolved store, date, status, or income-category references is not executable.
- Positive income may deterministically imply `营业`; a zero-income draft still requires an explicit status.
- Conversation history is stored and scoped to its owner; administrators do not receive an implicit conversation-history browsing endpoint.
- Assistant wording remains cautious, avoids absolute predictions, and does not invent percentage forecasts.
- All successful AI mutations create `operation_source=agent`, `requires_approval=true`, `approved=true` audit records.

---

## File Structure

```text
backend/
├── alembic/versions/0003_agent.py
├── app/models/agent.py
├── app/schemas/agent.py
├── app/services/{llm,agent_tools,agent_graph,agent_proposals}.py
├── app/api/routes/agent.py
└── tests/
    ├── services/{test_llm,test_agent_tools,test_agent_graph,test_agent_proposals}.py
    └── api/{test_agent,test_agent_security}.py
frontend/
├── src/components/agent/{AgentPanel,MessageList,ProposalCard}.tsx
├── src/pages/AgentPage.tsx
├── src/pages/AgentPage.test.tsx
├── src/pages/ChartsPage.tsx
└── tests/agent-approval.spec.ts
```

## Shared interfaces

```python
class LLMGateway(Protocol):
    async def structured(self, task: Literal["chat", "reasoning"], messages: list[BaseMessage], schema: type[T]) -> T: ...

AgentTools.query(store_scope: StoreScope, intent: ReadIntent) -> ReadResult
AgentProposalService.prepare(conversation, intent, actor) -> AgentProposal
AgentProposalService.execute(proposal_id: int, actor: User, confirm: bool) -> ExecutionResult
run_agent(conversation_id: int, user_text: str, actor: User) -> AgentTurnResult
```

```text
GET    /api/agent/conversations?store_id=
POST   /api/agent/conversations
GET    /api/agent/conversations/{conversation_id}/messages
POST   /api/agent/conversations/{conversation_id}/messages
POST   /api/agent/proposals/{proposal_id}/execute
POST   /api/agent/proposals/{proposal_id}/cancel
POST   /api/charts/{store_id}/ai-analysis
```

### Task 1: Persist conversations, messages, and one-time mutation proposals

**Files:**
- Create: `backend/app/models/agent.py`
- Create: `backend/alembic/versions/0003_agent.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_agent_schema.py`

**Interfaces:**
- Consumes: `User`, `Store`, and Phase 1 audit records.
- Produces: `AgentConversation`, `AgentMessage`, and internal safety table `AgentProposal` with status `pending|executed|cancelled|expired` and immutable canonical payload/preview JSON.

- [ ] **Step 1: Write failing schema and proposal-state tests**

```python
# backend/tests/test_agent_schema.py
from app.models.base import Base
import app.models.agent  # noqa: F401


def test_agent_tables_are_registered() -> None:
    assert {"agent_conversations", "agent_messages", "agent_proposals"} <= set(Base.metadata.tables)


def test_proposal_has_safety_fields() -> None:
    columns = Base.metadata.tables["agent_proposals"].c
    assert {"user_id", "store_id", "action", "payload_json", "preview_json",
            "payload_hash", "status", "expires_at", "executed_at", "audit_id"} <= set(columns.keys())
```

- [ ] **Step 2: Run schema tests and verify the agent model is absent**

Run: `cd backend && pytest tests/test_agent_schema.py -q`

Expected: FAIL importing `app.models.agent`.

- [ ] **Step 3: Define conversation, message, and proposal models**

```python
# backend/app/models/agent.py
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AgentConversation(Base):
    __tablename__ = "agent_conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    messages: Mapped[list["AgentMessage"]] = relationship(cascade="all, delete-orphan")


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("agent_conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (CheckConstraint("role in ('user','assistant','system')", name="role"),)


class AgentProposal(Base):
    __tablename__ = "agent_proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("agent_conversations.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    action: Mapped[str] = mapped_column(String(20))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    preview_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime]
    executed_at: Mapped[datetime | None]
    audit_id: Mapped[int | None] = mapped_column(ForeignKey("audit_log.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (
        CheckConstraint("action in ('create','update','delete')", name="action"),
        CheckConstraint("status in ('pending','executed','cancelled','expired')", name="status"),
    )
```

- [ ] **Step 4: Generate/apply the migration and verify metadata**

Run: `cd backend && alembic revision --autogenerate -m "agent conversations and proposals" && alembic upgrade head && pytest tests/test_agent_schema.py -q`

Expected: three agent tables are added and schema tests pass. Rename the generated file to `0003_agent.py` without changing its revision chain.

- [ ] **Step 5: Commit AI persistence**

```bash
git add backend/app/models backend/alembic backend/tests/test_agent_schema.py
git commit -m "feat: add agent conversation and proposal schema"
```

### Task 2: Isolate model providers behind a tested fallback gateway

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/services/llm.py`
- Create: `backend/tests/services/test_llm.py`

**Interfaces:**
- Consumes: DeepSeek and Qwen base URLs, model names, and API keys from secrets.
- Produces: `LLMGateway.structured(task, messages, schema)`, choosing V3 for `chat`, R1 for `reasoning`, and Qwen-Plus after DeepSeek failures.

- [ ] **Step 1: Write failing routing/fallback tests with fake models**

```python
# backend/tests/services/test_llm.py
class FakeModel:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0
    def with_structured_output(self, schema):
        self.schema = schema
        return self
    async def ainvoke(self, messages):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


async def test_chat_uses_v3_without_touching_fallback() -> None:
    gateway = LLMGateway(v3=FakeModel({"intent": "read"}), r1=FakeModel(), qwen=FakeModel())
    result = await gateway.structured("chat", [], IntentEnvelope)
    assert result.intent == "read"
    assert gateway.v3.calls == 1
    assert gateway.qwen.calls == 0


async def test_reasoning_falls_back_from_r1_to_qwen() -> None:
    gateway = LLMGateway(
        v3=FakeModel(), r1=FakeModel(error=TimeoutError()),
        qwen=FakeModel({"intent": "analysis"}),
    )
    result = await gateway.structured("reasoning", [], IntentEnvelope)
    assert result.intent == "analysis"
    assert gateway.r1.calls == 1
    assert gateway.qwen.calls == 1
```

- [ ] **Step 2: Run gateway tests and verify missing service failure**

Run: `cd backend && pytest tests/services/test_llm.py -q`

Expected: FAIL importing `app.services.llm`.

- [ ] **Step 3: Add dependencies/configuration and implement the gateway**

```toml
# append to backend/pyproject.toml dependencies
"langchain",
"langchain-openai",
"langgraph",
```

```python
# backend/app/services/llm.py
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class StructuredModel(Protocol):
    def with_structured_output(self, schema: type[T]): ...


class LLMGateway:
    def __init__(self, *, v3: StructuredModel, r1: StructuredModel, qwen: StructuredModel):
        self.v3, self.r1, self.qwen = v3, r1, qwen

    async def structured(self, task: Literal["chat", "reasoning"], messages: list, schema: type[T]) -> T:
        primary = self.v3 if task == "chat" else self.r1
        failures: list[Exception] = []
        for model in (primary, self.qwen):
            try:
                return await model.with_structured_output(schema).ainvoke(messages)
            except Exception as exc:
                failures.append(exc)
        raise RuntimeError("All configured LLM providers failed") from failures[-1]
```

Factory configuration uses `ChatOpenAI(model=settings.deepseek_v3_model, base_url=settings.deepseek_base_url, api_key=...)`, the equivalent R1 model, and a Qwen client with its own base URL/key. Secrets never appear in logs or API responses.

- [ ] **Step 4: Verify routing, fallback, and total-failure alert behavior**

On total failure, the caller creates one unresolved `system_alerts` row with `alert_type=ai_call_failed`, `level=error`, a sanitized provider/task message, and no prompt/API key. Repeated identical failures within one hour reuse the unresolved alert rather than flooding the admin list.

Run: `cd backend && pytest tests/services/test_llm.py -q`

Expected: V3/R1 routing, Qwen fallback, structured validation retry failure, sanitized error, and deduplicated alert tests pass.

- [ ] **Step 5: Commit the provider gateway**

```bash
git add backend/pyproject.toml backend/app/core/config.py backend/app/services/llm.py backend/tests/services/test_llm.py
git commit -m "feat: add resilient llm provider gateway"
```

### Task 3: Build permission-scoped read and analysis tools

**Files:**
- Create: `backend/app/schemas/agent.py`
- Create: `backend/app/services/agent_tools.py`
- Create: `backend/tests/services/test_agent_tools.py`
- Create: `backend/tests/api/test_agent_security.py`

**Interfaces:**
- Consumes: Phase 1 database filters/analytics services and explicit `StoreScope` from authorized backend code.
- Produces: typed read intents for interval summary, missing dates, extrema, category composition, weather/activity/weekday analysis, anomaly checks, and current-store summary.

- [ ] **Step 1: Write failing tool security and result tests**

```python
# backend/tests/services/test_agent_tools.py
from pydantic import TypeAdapter, ValidationError


async def test_interval_summary_delegates_to_authorized_store(agent_tools, assigned_scope) -> None:
    result = await agent_tools.query(assigned_scope, ReadIntent(
        kind="interval_summary", start=date(2026, 7, 1), end=date(2026, 7, 31),
    ))
    assert result.store_ids == [assigned_scope.current_store_id]
    assert result.data["total_revenue"] == "350.00"


async def test_regular_user_cannot_expand_scope(agent_tools, regular_scope) -> None:
    with pytest.raises(HTTPException) as error:
        await agent_tools.query(regular_scope.model_copy(update={"requested_store_ids": [1, 2]}),
                                ReadIntent(kind="interval_summary"))
    assert error.value.status_code == 403


async def test_model_cannot_supply_sql(agent_tools, assigned_scope) -> None:
    adapter = TypeAdapter(ReadIntent)
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "sql", "query": "select * from users"})
```

- [ ] **Step 2: Run read-tool tests and verify missing schemas/service**

Run: `cd backend && pytest tests/services/test_agent_tools.py tests/api/test_agent_security.py -q`

Expected: FAIL because agent schemas and tools do not exist.

- [ ] **Step 3: Define a closed intent union and store scope**

```python
# backend/app/schemas/agent.py
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class StoreScope(BaseModel):
    user_id: int
    role: Literal["admin", "user"]
    current_store_id: int
    allowed_store_ids: list[int]
    requested_store_ids: list[int]


class IntervalSummary(BaseModel):
    kind: Literal["interval_summary"]
    start: date
    end: date


class MissingDates(BaseModel):
    kind: Literal["missing_dates"]
    start: date
    end: date


class Extrema(BaseModel):
    kind: Literal["extrema"]
    start: date
    end: date


class QualitativeAnalysis(BaseModel):
    kind: Literal["analysis"]
    dimension: Literal["trend", "category", "weather", "activity", "weekday", "anomaly"]
    start: date
    end: date


ReadIntent = Annotated[
    IntervalSummary | MissingDates | Extrema | QualitativeAnalysis,
    Field(discriminator="kind"),
]
```

- [ ] **Step 4: Implement authorization before domain-service delegation**

`AgentTools.query` computes requested stores from the validated scope, rejects any id not in `allowed_store_ids`, and forces mutations elsewhere to `current_store_id`. For regular users, requested IDs must equal `[current_store_id]`; admins may read multiple allowed active stores. Each intent calls Phase 1 services with bound parameters and returns structured numbers plus evidence dates. The final formatter may describe trends but must not output a prediction percentage.

Run: `cd backend && pytest tests/services/test_agent_tools.py tests/api/test_agent_security.py -q`

Expected: summary, missing-date, extrema, six analysis dimensions, regular-user isolation, administrator cross-store read, closed intent union, and no-SQL tests pass.

- [ ] **Step 5: Commit read-only agent tools**

```bash
git add backend/app/schemas/agent.py backend/app/services/agent_tools.py backend/tests
git commit -m "feat: add permission-scoped agent read tools"
```

### Task 4: Build ledger draft normalization and immutable proposal previews

**Files:**
- Create: `backend/app/services/agent_proposals.py`
- Create: `backend/tests/services/test_agent_proposals.py`

**Interfaces:**
- Consumes: typed create/update/delete intents, current store, active/historical categories, existing ledger snapshot, and actor.
- Produces: canonical persisted proposal with five-minute expiry, SHA-256 payload hash, human-readable before/after preview, and explicit missing-field errors.

- [ ] **Step 1: Write failing normalization and safety tests**

```python
# backend/tests/services/test_agent_proposals.py
async def test_positive_income_implies_open_and_resolves_category_names(proposal_service, conversation, actor) -> None:
    proposal = await proposal_service.prepare(conversation, {
        "action": "create", "date": "2026-07-13",
        "items": [{"category_name": "现金", "amount": "200.00"}],
    }, actor)
    assert proposal.payload_json["is_open"] == "营业"
    assert proposal.payload_json["items"][0]["category_id"] == conversation.cash_category_id
    assert proposal.preview_json["after"]["daily_revenue"] == "200.00"


async def test_zero_income_without_status_is_not_executable(proposal_service, conversation, actor) -> None:
    with pytest.raises(HTTPException) as error:
        await proposal_service.prepare(conversation, {
            "action": "create", "date": "2026-07-13",
            "items": [{"category_name": "现金", "amount": "0.00"}],
        }, actor)
    assert error.value.detail == {"missing_fields": ["is_open"]}


async def test_total_revenue_field_is_rejected(proposal_service, conversation, actor) -> None:
    with pytest.raises(HTTPException) as error:
        await proposal_service.prepare(conversation, {
            "action": "update", "date": "2026-07-13", "daily_revenue": "999.00",
        }, actor)
    assert error.value.status_code == 422
```

- [ ] **Step 2: Run proposal tests and verify service failure**

Run: `cd backend && pytest tests/services/test_agent_proposals.py -q`

Expected: FAIL importing `app.services.agent_proposals`.

- [ ] **Step 3: Implement canonical hashing, expiry, and category resolution**

```python
# backend/app/services/agent_proposals.py
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from app.models.agent import AgentProposal
from app.models.ledger import IncomeCategory, StoreDailyRecord


def canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class AgentProposalService:
    def __init__(self, session):
        self.session = session

    async def prepare(self, conversation, intent: dict, actor) -> AgentProposal:
        if actor.id != conversation.user_id:
            raise HTTPException(404, "Conversation not found")
        if "daily_revenue" in intent:
            raise HTTPException(422, "AI cannot set total revenue")
        action = intent["action"]
        if action not in {"create", "update", "delete"}:
            raise HTTPException(422, "Unsupported mutation action")
        if not intent.get("date"):
            raise HTTPException(422, {"missing_fields": ["date"]})
        before = await load_ledger_snapshot(self.session, conversation.store_id, intent["date"])
        if action == "create" and before is not None:
            raise HTTPException(409, "Record already exists")
        if action in {"update", "delete"} and before is None:
            raise HTTPException(404, "Record not found")
        categories = (await self.session.scalars(select(IncomeCategory).where(
            IncomeCategory.store_id == conversation.store_id,
        ))).all()
        by_name = {category.name.casefold(): category for category in categories}
        supplied_items = intent.get("items")
        unresolved = [item["category_name"] for item in supplied_items or []
                      if item["category_name"].casefold() not in by_name]
        if unresolved:
            raise HTTPException(422, {"unknown_categories": unresolved})
        previous_ids = set() if before is None else {item["category_id"] for item in before["items"]}
        if any(
            not by_name[item["category_name"].casefold()].is_active
            and by_name[item["category_name"].casefold()].id not in previous_ids
            for item in supplied_items or []
        ):
            raise HTTPException(422, "Inactive categories cannot be added")
        if action == "delete":
            payload = {"date": intent["date"]}
        else:
            payload = {
                "date": intent["date"],
                "is_open": intent.get("is_open", None if before is None else before["is_open"]),
                "wash_count": intent.get("wash_count", None if before is None else before["wash_count"]),
                "weather": intent.get("weather", None if before is None else before["weather"]),
                "weather_edited": "weather" in intent or (False if before is None else before["weather_edited"]),
                "activity": intent.get("activity", None if before is None else before["activity"]),
                "items": (
                    [{"category_id": item["category_id"], "amount": item["amount"]}
                     for item in before["items"]]
                    if supplied_items is None and before is not None else [
                        {"category_id": by_name[item["category_name"].casefold()].id,
                         "amount": item["amount"]}
                        for item in supplied_items or []
                    ]
                ),
            }
        if action != "delete" and payload["is_open"] is None:
            if any(Decimal(item["amount"]) > 0 for item in payload["items"]):
                payload["is_open"] = "营业"
            else:
                raise HTTPException(422, {"missing_fields": ["is_open"]})
        if action == "create" and not payload["items"]:
            raise HTTPException(422, {"missing_fields": ["items"]})
        preview = await preview_change(self.session, conversation.store_id, action, payload, before)
        proposal = AgentProposal(
            conversation_id=conversation.id, user_id=actor.id, store_id=conversation.store_id,
            action=action, payload_json=payload, preview_json=preview,
            payload_hash=canonical_hash(payload), status="pending",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        self.session.add(proposal)
        await self.session.commit()
        return proposal
```

- [ ] **Step 4: Complete create/update/delete preview rules and verify tests**

Create requires no existing record; update/delete require one. Update merges omitted optional fields with the current snapshot, but every referenced category must belong to the conversation store; inactive historical categories are accepted only when already present on that record. Preview recomputes revenue from category flags and contains `before`, `after`, `action`, `store_id`, `date`, and a concise description. Delete has `after=null`. The persisted payload cannot be edited after insertion.

Run: `cd backend && pytest tests/services/test_agent_proposals.py -q`

Expected: category resolution, positive-income status inference, zero-income missing status, create/update/delete preconditions, total protection, store locking, preview totals, canonical hash, and expiry tests pass.

- [ ] **Step 5: Commit agent proposal preparation**

```bash
git add backend/app/services/agent_proposals.py backend/tests/services/test_agent_proposals.py
git commit -m "feat: add validated agent mutation proposals"
```

### Task 5: Orchestrate conversations and execute proposals exactly once

**Files:**
- Create: `backend/app/services/agent_graph.py`
- Create: `backend/app/api/routes/agent.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/services/ledger.py`
- Modify: `backend/app/services/audit.py`
- Create: `backend/tests/services/test_agent_graph.py`
- Create: `backend/tests/api/test_agent.py`
- Modify: `backend/tests/api/test_agent_security.py`

**Interfaces:**
- Consumes: LLM structured intents, AgentTools, AgentProposalService, ledger write/delete service, conversation owner, and store access.
- Produces: LangGraph turn result (`answer|proposal|needs_input`), persisted messages, one-time execution/cancel endpoints, and chart-analysis endpoint.

- [ ] **Step 1: Write failing direct-read, approval, replay, and expiry tests**

```python
# backend/tests/api/test_agent.py
async def test_read_answer_needs_no_confirmation(agent_client, conversation, fake_llm) -> None:
    fake_llm.returns_read_summary()
    response = await agent_client.post(f"/api/agent/conversations/{conversation.id}/messages", json={
        "content": "这个月收入多少？",
    })
    assert response.status_code == 200
    assert response.json()["kind"] == "answer"
    assert response.json()["proposal"] is None


async def test_mutation_is_unchanged_until_confirmed(agent_client, conversation, fake_llm, ledger_repo) -> None:
    fake_llm.returns_create(date="2026-07-13", cash="200.00")
    turn = (await agent_client.post(f"/api/agent/conversations/{conversation.id}/messages", json={
        "content": "今天现金200",
    })).json()
    assert turn["kind"] == "proposal"
    assert await ledger_repo.for_date(conversation.store_id, "2026-07-13") is None
    executed = await agent_client.post(f"/api/agent/proposals/{turn['proposal']['id']}/execute", json={"confirm": True})
    assert executed.status_code == 200
    assert (await ledger_repo.for_date(conversation.store_id, "2026-07-13")).daily_revenue == Decimal("200.00")
    replay = await agent_client.post(f"/api/agent/proposals/{turn['proposal']['id']}/execute", json={"confirm": True})
    assert replay.status_code == 409
```

- [ ] **Step 2: Run graph/API tests and verify orchestration is missing**

Run: `cd backend && pytest tests/services/test_agent_graph.py tests/api/test_agent.py tests/api/test_agent_security.py -q`

Expected: FAIL because graph and routes do not exist.

- [ ] **Step 3: Implement a closed LangGraph state machine**

```python
# backend/app/services/agent_graph.py
from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph


class AgentState(TypedDict):
    conversation_id: int
    user_text: str
    intent: dict | None
    result: dict | None
    route: Literal["read", "write", "needs_input"] | None


def build_agent_graph(classify, run_read, prepare_write, request_input):
    graph = StateGraph(AgentState)
    graph.add_node("classify", classify)
    graph.add_node("read", run_read)
    graph.add_node("write", prepare_write)
    graph.add_node("needs_input", request_input)
    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", lambda state: state["route"], {
        "read": "read", "write": "write", "needs_input": "needs_input",
    })
    graph.add_edge("read", END)
    graph.add_edge("write", END)
    graph.add_edge("needs_input", END)
    return graph.compile()
```

The classifier output is a discriminated Pydantic union; unknown output becomes `needs_input`, never a write. Persist the user message before graph invocation and the assistant result afterward. History queries require `conversation.user_id == current_user.id` and matching store access.

- [ ] **Step 4: Implement locked proposal execution and audit proof**

Execution loads `AgentProposal ... FOR UPDATE`, verifies owner, active store access, `status=pending`, unexpired time, `confirm=true`, and `canonical_hash(payload_json)==payload_hash`. It calls the Phase 1 ledger service with `source="agent"`, `requires_approval=True`, and `approved=True`; create/update use the proposal payload and delete uses the existing delete method. Then it sets `status=executed`, `executed_at`, and `audit_id` in the same transaction. Cancel only moves `pending` to `cancelled`. Expired proposals move to `expired` and return 410. Chart analysis uses the currently filtered structured analytics payload, never asks the model to refetch unrestricted data.

Run: `cd backend && pytest tests/services/test_agent_graph.py tests/api/test_agent.py tests/api/test_agent_security.py -q`

Expected: read, analysis, needs-input, proposal, confirmation, cancel, expiry, hash mismatch, owner isolation, store isolation, replay protection, conversation history, chart analysis, and approved-agent-audit tests pass.

- [ ] **Step 5: Commit secure agent orchestration**

```bash
git add backend/app/services backend/app/api/routes/agent.py backend/app/api/router.py backend/tests
git commit -m "feat: add approval-gated agent orchestration"
```

### Task 6: Build the assistant UI and Phase 3 release gate

**Files:**
- Create: `frontend/src/components/agent/AgentPanel.tsx`
- Create: `frontend/src/components/agent/MessageList.tsx`
- Create: `frontend/src/components/agent/ProposalCard.tsx`
- Create: `frontend/src/pages/AgentPage.tsx`
- Create: `frontend/src/pages/AgentPage.test.tsx`
- Modify: `frontend/src/pages/ChartsPage.tsx`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/layouts/AppShell.tsx`
- Create: `frontend/tests/agent-approval.spec.ts`
- Modify: `.env.example`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: conversation/message/proposal/analysis APIs.
- Produces: store-bound conversation UI, visible mutation diff, confirm/cancel controls, disabled expired/executed proposals, chart analysis action, and provider configuration documentation.

- [ ] **Step 1: Write failing proposal-card and conversation tests**

```tsx
// frontend/src/pages/AgentPage.test.tsx
it("renders a mutation preview and never executes before confirmation", async () => {
  renderAgentPage(proposalFixture({ action: "update", before: { cash: "100.00" }, after: { cash: "120.00" } }));
  expect(await screen.findByText("现金：€100.00 → €120.00")).toBeInTheDocument();
  expect(executeSpy).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "确认修改" }));
  expect(executeSpy).toHaveBeenCalledTimes(1);
});


it("switching store starts or selects a conversation for that store", async () => {
  const view = renderAgentPage(answerFixture(), { storeId: 1 });
  await view.selectStore(2);
  expect(await screen.findByText("当前店铺：Second Store")).toBeInTheDocument();
  expect(screen.queryByText("First Store private message")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run UI tests and verify assistant components are missing**

Run: `cd frontend && npm test -- AgentPage`

Expected: FAIL because assistant page/components do not exist.

- [ ] **Step 3: Implement conversation and proposal UI states**

`AgentPage` binds its query keys to selected store and conversation. `MessageList` distinguishes user/assistant/system messages and renders cautious analysis as text plus evidence dates. `ProposalCard` displays action, date, each changed field/category, calculated total, expiry, and server error; it provides explicit confirm/cancel buttons and disables both after a terminal status. It never optimistically updates ledger data; after execution it invalidates ledger, database, charts, dashboard, audit history, and proposal/message queries.

- [ ] **Step 4: Verify UI, backend, secret handling, and provider-failure behavior**

Add only variable names to `.env.example`: DeepSeek base URL, V3 model, R1 model, API key, Qwen base URL, model, and API key. CI uses fake `LLMGateway` tests and makes no paid provider calls. README documents model roles, approval safety, proposal expiry, store scope, and alert behavior.

Run: `cd backend && ruff check . && pytest --cov=app; cd ../frontend && npm test && npm run build && npx playwright test tests/agent-approval.spec.ts; cd .. && docker compose config && docker compose build`

Expected: all tests pass; Playwright proves no write request before confirmation, one write after confirmation, replay remains disabled, store switching hides prior history, chart analysis uses active filters, no secrets appear in built frontend assets, and images build.

- [ ] **Step 5: Commit the Phase 3 release**

```bash
git add frontend .env.example .github/workflows/ci.yml README.md
git commit -m "feat: add safe agent conversation interface"
```

## Phase 3 acceptance checklist

- DeepSeek-V3 and R1 are selected by task type; Qwen-Plus is used only after the selected DeepSeek model fails.
- All model output is validated as a closed typed intent before any domain operation.
- Regular users cannot query another store; administrators may analyze multiple allowed stores but every proposal is locked to the conversation store.
- Read-only answers need no approval and mutations cannot change data before explicit confirmation.
- Proposal payloads are immutable, hashed, expiring, owner-scoped, and executable exactly once.
- Total revenue is never accepted from the model and remains a ledger-service calculation.
- Every successful mutation links to an approved agent audit entry; failure alerts contain no prompts, tokens, or keys.
- Conversation history is persisted and visible only to its owner.
