from typing import TypedDict

from app.agents.context import ChatScope


class AssistantState(TypedDict):
    scope: ChatScope
    run_id: str
    messages: list[dict]
