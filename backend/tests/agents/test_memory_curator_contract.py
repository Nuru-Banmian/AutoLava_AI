"""Replay #248 call 81/84 at the real graph -> provider boundary, without network.

These are input-contract tests, not evidence that a live model will obey the prompt.
The boundary observer never invents a successful reject or commits a proposal.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.agents.memory_curator.graph import create_memory_graph
from app.agents.providers.bailian import ToolCall
from app.agents.registry import memory_capabilities
from tests.api.test_agent_chat import StreamingModel, chat_app
from tests.api.test_agent_memory import save
from tests.api.test_memory_jobs import BackgroundCurator, settled, turn


ACTIVE = [
    {"id": "490478089dea483aafbe6f70be7410fd", "version": 1,
     "content": "以后给我经营建议时，金额统一写成欧元，最多列两点。",
     "category": "preference", "status": "active"},
    {"id": "faea8e26fbd24a18a13f0da10428e07f", "version": 2,
     "content": "以后分析先展示关键数据，最后再说结论。",
     "category": "preference", "status": "active"},
]
PENDING = [
    {"id": "3f09c90198d145c988d6f7105c45bfa5", "version": 1,
     "content": "用户偏好经营数据总结的篇幅和顺序，但未明确说明具体篇幅和顺序细节",
     "category": "preference", "status": "pending_confirmation"},
    {"id": "ff69ee02308a4da798ef15d7a5bd3085", "version": 1,
     "content": "用户偏好经营数据总结的篇幅和顺序",
     "category": "preference", "status": "pending_confirmation"},
]
REAL_TURNS = [
    (81, "花店，主营鲜切花和婚礼花艺。", 16,
     "请根据当前门店背景解释2026年10月1日至2日经营情况，说明能否计算平均每车收入，并沿用我惯用的篇幅和顺序。"),
    (84, "", 17,
     "请分析2026年10月1日至2日经营情况，目前能确定主营业务和平均每车收入吗？沿用我惯用的篇幅和顺序。"),
]


class BoundaryObserved(Exception):
    """Stop immediately after inspecting the actual provider call arguments."""


class SnapshotJobs:
    def __init__(self, snapshot):
        self.value = snapshot
        self.records = []

    async def snapshot(self, scope, job_id):
        return deepcopy(self.value)

    async def record(self, scope, job_id, kind, payload):
        self.records.append((kind, payload))


def schema_values(schema, kind):
    """Read permitted scalar values from the provider's nullable target property."""
    if "enum" in schema:
        scalar = str if kind == "string" else int
        return [value for value in schema["enum"] if isinstance(value, scalar)]
    branches = schema.get("anyOf", [schema])
    matching = [branch for branch in branches if branch.get("type") == kind]
    if not matching and all(branch.get("type") == "null" for branch in branches):
        return []
    assert len(matching) == 1, schema
    return matching[0].get("enum")


@pytest.mark.parametrize("call,description,revision,input_text", REAL_TURNS,
                         ids=["call81-florist", "call84-cleared"])
@pytest.mark.parametrize("contract", ["target_ids", "target_versions", "active_context"])
async def test_real_failed_turns_exclude_pending_targets_at_provider_boundary(
    call, description, revision, input_text, contract,
):
    # Minimized from the two saved provider requests: preserve every memory,
    # the complete current input, and description revision; history is irrelevant
    # to target authorization. The original full requests remain untouched.
    snapshot = {
        "input": input_text, "message_id": 28 if call == 81 else 30,
        "conversation": [{"message_id": 1, "content": input_text}],
        "description": description, "description_revision": revision,
        "mode": "background", "memories": deepcopy([PENDING[0], *ACTIVE, PENDING[1]]),
    }
    replay = {"action": "duplicate", "content": PENDING[1]["content"],
              "category": "preference", "target_id": PENDING[1]["id"],
              "target_version": 1, "evidence": input_text}

    class BoundaryProvider:
        model_name = "offline-call-81-84-boundary-observer"

        async def stream_tools(self, messages, tools):
            actual = json.loads(messages[-1]["content"])
            assert actual["input"] == replay["evidence"]
            assert len(tools) == 1 and tools[0]["function"]["name"] == "propose_memory"
            properties = tools[0]["function"]["parameters"]["properties"]
            if contract == "target_ids":
                allowed = schema_values(properties["target_id"], "string")
                assert allowed is not None, "call 81/84 pending target is still schema-permitted"
                assert set(allowed) == {memory["id"] for memory in ACTIVE}
                assert replay["target_id"] not in allowed
            elif contract == "target_versions":
                allowed = schema_values(properties["target_version"], "integer")
                assert allowed is not None, "target versions are not scoped to active snapshot"
                assert set(allowed) == {memory["version"] for memory in ACTIVE}
            else:
                assert all(memory["status"] == "active" for memory in actual["memories"]), (
                    "call 81/84 pending candidates are mixed into the model's effective memories"
                )
                assert {memory["id"] for memory in actual["memories"]} == {
                    memory["id"] for memory in ACTIVE
                }
                assert actual["pending_candidates"] == PENDING
            raise BoundaryObserved
            yield  # Make this the same async-generator interface as the real provider.

    jobs = SnapshotJobs(snapshot)
    settings = SimpleNamespace(agent_memory_context_chars=30000,
                               agent_memory_max_calls=1, agent_memory_output_chars=4000)
    graph = create_memory_graph(BoundaryProvider(), object(), settings, jobs=jobs)
    with pytest.raises(BoundaryObserved):
        await graph.ainvoke({"scope": object(), "run_id": "replay", "job_id": call})
    assert len(jobs.records) == 1 and jobs.records[0][0] == "memory_attempt"
    assert jobs.value == snapshot


async def test_background_duplicate_cannot_add_vague_reference_as_active_source(tmp_path):
    """Prove the repeated-source hypothesis with an offline public-service replay."""
    curator = BackgroundCurator()
    async with chat_app(tmp_path, StreamingModel(), memory_model=curator) as (client, app, _):
        await save(client)
        before = (await client.get("/api/agent/1/memories")).json()
        active = before["items"][0]
        assert active["status"] == "active" and len(active["sources"]) == 1
        curator.action, curator.content = "duplicate", active["content"]
        curator.target = {"target_id": active["id"], "target_version": active["version"]}
        await app.state.agent_runner.jobs.start()
        run = await turn(client, REAL_TURNS[0][3])
        job = await settled(client, run["id"])
        assert job["status"] == "failed" and job["error_code"] == "memory_invalid_proposal", job
        assert (await client.get("/api/agent/1/memories")).json() == before
        assert (await client.get(f'/api/agent/1/runs/{run["id"]}')).json()["status"] == "completed"


@pytest.mark.parametrize("memories", [[], PENDING], ids=["empty", "only-pending"])
async def test_no_active_memory_schema_forbids_duplicate_and_update_without_mutating_tools(memories):
    tools = memory_capabilities()
    original = deepcopy(tools)
    snapshot = {"input": "你好", "mode": "background", "memories": deepcopy(memories)}

    class NoTargetProvider:
        model_name = "offline-no-active-boundary-observer"

        async def stream_tools(self, messages, supplied_tools):
            properties = supplied_tools[0]["function"]["parameters"]["properties"]
            assert schema_values(properties["target_id"], "string") == []
            assert schema_values(properties["target_version"], "integer") == []
            assert set(properties["action"]["enum"]) == {"save", "conflict", "infer", "reject"}
            actual = json.loads(messages[-1]["content"])
            assert actual["memories"] == [] and actual["pending_candidates"] == memories
            raise BoundaryObserved
            yield

    settings = SimpleNamespace(agent_memory_context_chars=30000,
                               agent_memory_max_calls=1, agent_memory_output_chars=4000)
    graph = create_memory_graph(NoTargetProvider(), object(), settings,
                                agent_capabilities=tools, jobs=SnapshotJobs(snapshot))
    with pytest.raises(BoundaryObserved):
        await graph.ainvoke({"scope": object(), "run_id": "no-target", "job_id": 1})
    assert tools == original


async def test_background_invalid_targets_and_source_stay_failed_but_valid_duplicate_merges(tmp_path):
    class EvidenceCurator(BackgroundCurator):
        evidence = None
        category = "preference"

        async def stream_tools(self, messages, tools):
            snapshot = json.loads(messages[-1]["content"])
            self.calls.append(snapshot)
            raw = snapshot["input"]
            yield ToolCall("proposal", "propose_memory", json.dumps({
                "action": self.action, "category": self.category,
                "content": self.content or (raw if snapshot.get("mode") == "background"
                                            else raw.split("：", 1)[-1]),
                **({"evidence": self.evidence if self.evidence is not None else raw}
                   if snapshot.get("mode") == "background" else {}), **self.target,
            }, ensure_ascii=False))

    curator = EvidenceCurator()
    async with chat_app(tmp_path, StreamingModel(), memory_model=curator) as (client, app, _):
        await save(client)
        active = (await client.get("/api/agent/1/memories")).json()["items"][0]
        await app.state.agent_runner.jobs.start()
        curator.action, curator.content = "infer", "用户可能偏好很短的总结"
        candidate_run = await turn(client, "我在考虑另一种篇幅")
        assert (await settled(client, candidate_run["id"]))["result"]["status"] == "pending_confirmation"
        before = (await client.get("/api/agent/1/memories")).json()
        pending = next(item for item in before["items"] if item["status"] == "pending_confirmation")
        curator.action, curator.content = "duplicate", active["content"]
        valid_target = {"target_id": active["id"], "target_version": active["version"]}
        invalid = [
            ({"target_id": pending["id"], "target_version": pending["version"]}, "preference", None),
            ({**valid_target, "target_version": active["version"] + 1}, "preference", None),
            (valid_target, "store_background", None),
            (valid_target, "preference", "以后分析先给结论，再列数据"),
        ]
        for target, category, evidence in invalid:
            curator.target, curator.category, curator.evidence = target, category, evidence
            run = await turn(client, "以后请先说结论再展示数据")
            job = await settled(client, run["id"])
            assert job["status"] == "failed" and job["error_code"] == "memory_invalid_proposal", job
            assert (await client.get("/api/agent/1/memories")).json() == before
            assert (await client.get(f'/api/agent/1/runs/{run["id"]}')).json()["status"] == "completed"

        curator.target, curator.category, curator.evidence = valid_target, "preference", None
        run = await turn(client, "以后请先说结论再展示数据")
        assert (await settled(client, run["id"]))["result"]["status"] == "saved"
        after = (await client.get("/api/agent/1/memories")).json()["items"]
        merged = next(item for item in after if item["id"] == active["id"])
        assert merged["status"] == "active" and merged["version"] == active["version"]
        assert merged["content"] == active["content"] and len(merged["sources"]) == 2
        assert merged["sources"][0]["evidence"] == "以后请先说结论再展示数据"
        assert next(item for item in after if item["id"] == pending["id"]) == pending
        assert (await client.get("/api/agent/2/memories")).json()["items"] == []
