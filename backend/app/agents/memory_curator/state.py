from typing import NotRequired, TypedDict

from app.agents.context import ChatScope


class CuratorState(TypedDict):
    scope: ChatScope
    run_id: str
    snapshot: dict
    result: dict
    job_id: NotRequired[int]
