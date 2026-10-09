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
    def record_read(self, reference: str, start: int, end: int) -> None: ...
    def read_ranges(self, reference: str) -> list[dict[str, int]]: ...
    def prepare_charts(self, drafts: list[dict]) -> None: ...
    def prepared_charts(self) -> list[dict]: ...
    def clear(self) -> None: ...


class RunResults:
    """Opaque references and immutable JSON copies; no business DB reads or persistence."""

    def __init__(self, scope: ChatScope | None = None, run_id: str | None = None,
                 generation: int | None = None):
        self._values: dict[str, bytes] = {}
        self._row_counts: dict[str, int] = {}
        self._read: dict[str, list[tuple[int, int]]] = {}
        self._size = 0
        self._closed = False
        self._charts: list[dict] = []

    def put(self, value: dict) -> str:
        if self._closed:
            raise RuntimeError("Run results already released")
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if self._size + len(data) > 4 * 1024 * 1024:
            raise ResultCapacityError("Temporary results exceed 4 MiB")
        reference = uuid4().hex
        self._values[reference] = data
        comparison = value.get("comparison") or {}
        self._row_counts[reference] = max(len(value.get("rows", [])),
                                          len(comparison.get("rows", [])))
        self._read[reference] = []
        self._size += len(data)
        return reference

    def get(self, reference: str) -> dict | None:
        data = self._values.get(reference)
        return json.loads(data) if data is not None else None

    def record_read(self, reference: str, start: int, end: int) -> None:
        """Record only successfully returned rows, using zero-based half-open bounds."""
        if (reference not in self._values or type(start) is not int or type(end) is not int
                or not 0 <= start <= end <= self._row_counts[reference]):
            raise ValueError("Invalid result read range")
        if start == end:
            return
        merged = []
        for left, right in sorted([*self._read[reference], (start, end)]):
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
            else:
                merged.append((left, right))
        self._read[reference] = merged

    def read_ranges(self, reference: str) -> list[dict[str, int]]:
        """One-based inclusive ranges; retries never count already returned rows twice."""
        return [{"start": left + 1, "end": right} for left, right in self._read.get(reference, [])]

    def clear(self) -> None:
        self._closed = True
        self._values.clear()
        self._row_counts.clear()
        self._read.clear()
        self._size = 0
        self._charts.clear()

    def prepare_charts(self, drafts: list[dict]) -> None:
        if (self._closed or len(drafts) > 8 or len(self._charts) + len(drafts) > 8
                or sum(item["byte_size"] for item in [*self._charts, *drafts]) > 512 * 1024):
            raise ValueError("chart_capacity_exceeded")
        self._charts.extend(json.loads(json.dumps(drafts, ensure_ascii=False, allow_nan=False)))

    def prepared_charts(self) -> list[dict]:
        return json.loads(json.dumps(self._charts, ensure_ascii=False, allow_nan=False))


class TemporaryResults:
    def __init__(self):
        self._runs: dict[str, tuple[ChatScope, int, RunResults]] = {}

    def for_run(self, scope: ChatScope, run_id: str, generation: int) -> RunResults:
        if run_id not in self._runs:
            self._runs[run_id] = (scope, generation, RunResults(scope, run_id, generation))
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
    catalogs: object | None = None
    remaining_context_chars: int | None = None
    question: str = ""
