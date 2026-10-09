"""Server-owned tool context and a run-local temporary repository interface."""

import json
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from app.agents.context import ChatScope


class ResultCapacityError(Exception):
    """A complete result cannot fit in this run's temporary storage."""


class ResultRepository(Protocol):
    def put(self, value: dict) -> str: ...
    def get(self, reference: str) -> dict | None: ...
    def clear(self) -> None: ...


class RunResults:
    """Opaque references and immutable JSON copies; no business DB reads or persistence."""

    def __init__(self):
        self._values: dict[str, bytes] = {}
        self._size = 0
        self._closed = False

    def put(self, value: dict) -> str:
        if self._closed:
            raise RuntimeError("Run results already released")
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if self._size + len(data) > 4 * 1024 * 1024:
            raise ResultCapacityError("Temporary results exceed 4 MiB")
        reference = uuid4().hex
        self._values[reference] = data
        self._size += len(data)
        return reference

    def get(self, reference: str) -> dict | None:
        data = self._values.get(reference)
        return json.loads(data) if data is not None else None

    def clear(self) -> None:
        self._closed = True
        self._values.clear()
        self._size = 0


class TemporaryResults:
    def __init__(self):
        self._runs: dict[str, tuple[ChatScope, int, RunResults]] = {}

    def for_run(self, scope: ChatScope, run_id: str, generation: int) -> RunResults:
        if run_id not in self._runs:
            self._runs[run_id] = (scope, generation, RunResults())
        owner, version, repository = self._runs[run_id]
        if owner != scope or version != generation:
            raise RuntimeError("Run results scope mismatch")
        return repository

    def release(self, run_id: str) -> None:
        if item := self._runs.pop(run_id, None):
            item[2].clear()


@dataclass(frozen=True)
class ToolContext:
    scope: ChatScope
    run_id: str
    generation: int
    remaining_result_chars: int
    results: ResultRepository
